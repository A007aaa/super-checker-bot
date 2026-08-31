import os
import logging
import asyncio
import tempfile
import time
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_balance_master, check_seeds_bulk
from tools.seed_extractor import SeedExtractor
import storage
import telegram.error

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN não definido.")

_allowed_raw = os.getenv("ALLOWED_USER_ID", "0").strip() or "0"
try:
    ALLOWED_USER_ID = int(_allowed_raw)
except ValueError:
    ALLOWED_USER_ID = 0

try:
    storage.init_db()
except Exception as e:
    logger.error(f"storage init: {e}")

user_pools: dict[int, list[str]] = {}
_running_checks: set[int] = set()
_cancel_flags: dict[int, bool] = {}
_job_started_at: dict[int, float] = {}

TELEGRAM_MAX_CHARS = 4096
TELEGRAM_MIN_INTERVAL = max(0.0, float(os.getenv("TELEGRAM_MIN_INTERVAL", "1.1")))
# Teto para o sleep de RetryAfter: nunca segure o lock do chat por mais que isso,
# senão comandos como /cancel e /start ficam travados esperando o mesmo lock.
TELEGRAM_MAX_RETRY_AFTER = max(1.0, float(os.getenv("TELEGRAM_MAX_RETRY_AFTER", "15")))
# Tempo máximo esperando o lock do chat antes de desistir (evita travar comandos
# de controle atrás de um job com um lock preso).
TELEGRAM_LOCK_TIMEOUT = max(1.0, float(os.getenv("TELEGRAM_LOCK_TIMEOUT", "20")))
_telegram_locks: dict[int, asyncio.Lock] = {}
_telegram_last_action: dict[int, float] = {}
SEED_WORKERS = max(1, int(os.getenv("SEED_WORKERS", "40")))
BATCH_SIZE = max(1, int(os.getenv("BATCH_SIZE", "500")))
MAX_FILE_CHARS = int(os.getenv("MAX_FILE_CHARS", str(20_000_000)))
MAX_SEEDS = max(1, int(os.getenv("MAX_SEEDS", "2000000")))

RAILWAY_DOMAIN = (os.getenv("RAILWAY_PUBLIC_DOMAIN") or "").strip().rstrip(";")
# path ESTÁVEL (não muda a cada restart)
WEBHOOK_PATH = (os.getenv("WEBHOOK_PATH") or "telegram/webhook").strip().strip("/")
PORT = int(os.getenv("PORT", "8080"))

NETWORK_LABELS = {
    "BTC": "Bitcoin (BTC)",
    "ETH": "Ethereum (ETH)",
    "BNB": "BNB (BSC)",
    "MATIC": "Polygon (MATIC)",
    "USDT_ETH": "USDT (Ethereum)",
    "USDT_BSC": "USDT (BSC)",
    "USDT_POLYGON": "USDT (Polygon)",
    "SOL": "Solana (SOL)",
    "TRX": "Tron (TRX)",
    "USDT_TRX": "USDT (Tron TRC-20)",
    "USDC_TRX": "USDC (Tron TRC-20)",
}

TEST_SEED = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)


def format_found_message(value: str, balances: list) -> str:
    lines = []
    for coin, addr, bal in balances:
        label = NETWORK_LABELS.get(coin, coin)
        lines.append(f"• {label}\n  Saldo: {bal}\n  `{addr}`")
    msg = (
        f"🎯 SALDO ENCONTRADO!\n\n"
        f"SEED:\n{value}\n\n"
        f"💰 Redes:\n\n" + "\n\n".join(lines)
    )
    if len(msg) > TELEGRAM_MAX_CHARS:
        msg = msg[: TELEGRAM_MAX_CHARS - 3] + "..."
    return msg


async def is_authorized(update: Update) -> bool:
    if not update or not update.effective_user:
        return False
    if ALLOWED_USER_ID == 0:
        return True
    return update.effective_user.id == ALLOWED_USER_ID


async def _wait_telegram_slot(chat_id: int):
    if TELEGRAM_MIN_INTERVAL <= 0:
        return
    last = _telegram_last_action.get(chat_id, 0.0)
    delay = TELEGRAM_MIN_INTERVAL - (time.monotonic() - last)
    if delay > 0:
        await asyncio.sleep(delay)
    _telegram_last_action[chat_id] = time.monotonic()


async def _acquire_chat_lock(chat_id: int) -> asyncio.Lock | None:
    """Pega o lock do chat com timeout, pra um job travado nunca bloquear
    comandos novos (ex: /cancel) pra sempre."""
    lock = _telegram_locks.setdefault(chat_id, asyncio.Lock())
    try:
        await asyncio.wait_for(lock.acquire(), timeout=TELEGRAM_LOCK_TIMEOUT)
        return lock
    except asyncio.TimeoutError:
        logger.warning(f"telegram lock timeout chat={chat_id}; seguindo sem lock")
        return None


async def _sleep_retry_after(e: "telegram.error.RetryAfter", chat_id: int) -> bool:
    """Espera o RetryAfter até um teto. Retorna False (e não espera) se o
    Telegram pedir mais que o teto, pra não segurar o lock indefinidamente."""
    wait = max(0, e.retry_after)
    if wait > TELEGRAM_MAX_RETRY_AFTER:
        logger.warning(
            f"chat={chat_id}: RetryAfter pediu {wait}s (> teto {TELEGRAM_MAX_RETRY_AFTER}s); "
            "desistindo desse envio pra não travar o bot"
        )
        return False
    await asyncio.sleep(wait)
    return True


async def safe_send(context, chat_id: int, text: str):
    lock = await _acquire_chat_lock(chat_id)
    try:
        try:
            await _wait_telegram_slot(chat_id)
            return await context.bot.send_message(chat_id=chat_id, text=text)
        except telegram.error.RetryAfter as e:
            if not await _sleep_retry_after(e, chat_id):
                return None
            try:
                await _wait_telegram_slot(chat_id)
                return await context.bot.send_message(chat_id=chat_id, text=text)
            except Exception:
                return None
        except Exception as e:
            logger.exception(f"send: {e}")
            return None
    finally:
        if lock is not None:
            lock.release()


async def safe_edit(message, text: str):
    if message is None:
        return None
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    if chat_id is None:
        chat_id = getattr(message, "chat_id", 0) or 0
    lock = await _acquire_chat_lock(chat_id)
    try:
        try:
            await _wait_telegram_slot(chat_id)
            return await message.edit_text(text)
        except telegram.error.RetryAfter as e:
            if not await _sleep_retry_after(e, chat_id):
                return message
            try:
                await _wait_telegram_slot(chat_id)
                return await message.edit_text(text)
            except Exception:
                return message
        except Exception:
            return message
    finally:
        if lock is not None:
            lock.release()


def _unlock(user_id: int):
    _running_checks.discard(user_id)
    _cancel_flags.pop(user_id, None)
    _job_started_at.pop(user_id, None)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    await safe_send(
        context,
        update.effective_chat.id,
        "🚀 Super Checker\n\n"
        f"• {SEED_WORKERS} workers | lotes {BATCH_SIZE}\n"
        f"• até {MAX_SEEDS:,} seeds/run\n"
        "/check /cancel /clear /test",
    )


async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    user_pools[update.effective_user.id] = []
    await safe_send(context, update.effective_chat.id, "🗑️ Memória limpa.")


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    user_id = update.effective_user.id
    _cancel_flags[user_id] = True
    was = user_id in _running_checks
    _unlock(user_id)
    if was:
        await safe_send(context, update.effective_chat.id, "🛑 Cancelado / lock liberado. Pode /check.")
    else:
        await safe_send(context, update.effective_chat.id, "✅ Nenhum job ativo. Pode /check.")


async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    chat_id = update.effective_chat.id
    status = await safe_send(context, chat_id, "🧪 Teste...")
    try:
        res = await check_balance_master("SEED", TEST_SEED)
        if res:
            await safe_edit(status, "✅ Bot OK!\n\n" + format_found_message(TEST_SEED, res[1]))
        else:
            await safe_edit(status, "⚠️ Checker respondeu, sem saldo na seed de teste (RPC?).")
    except Exception as e:
        logger.exception("test")
        await safe_edit(status, f"❌ Falha no checker: {e}")


async def _run_check_job(context, chat_id: int, user_id: int, full_text: str, status_msg):
    _cancel_flags[user_id] = False
    _job_started_at[user_id] = time.time()
    try:
        await safe_edit(status_msg, "🔍 Extraindo seeds BIP39...")
        extractor = SeedExtractor()
        try:
            stats = await asyncio.wait_for(
                asyncio.to_thread(extractor.extract_with_stats, full_text),
                timeout=120,
            )
        except asyncio.TimeoutError:
            await safe_edit(status_msg, "❌ Extração demorou >2min. Texto muito grande?")
            return

        seeds = stats.valid
        if not seeds:
            await safe_edit(
                status_msg,
                f"⚠️ Nenhuma seed BIP39 válida.\nPalavras BIP39: {stats.total_words}\n"
                f"Janelas: {getattr(stats, 'windows_scanned', '?')}",
            )
            return

        total_all = len(seeds)
        if total_all > MAX_SEEDS:
            seeds = seeds[:MAX_SEEDS]
            await safe_send(context, chat_id, f"⚠️ {total_all:,} → limitando a {MAX_SEEDS:,}")

        total = len(seeds)
        n_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

        await safe_edit(
            status_msg,
            f"✅ {total:,} seeds | {n_batches} lote(s) | {SEED_WORKERS} workers\n🔄 checando...",
        )

        found_count = zero_count = error_count = checked = 0
        last_progress_at = 0.0
        cancelled = False

        for batch_i in range(n_batches):
            if _cancel_flags.get(user_id):
                cancelled = True
                break
            batch = seeds[batch_i * BATCH_SIZE : (batch_i + 1) * BATCH_SIZE]

            async for seed, res, err in check_seeds_bulk(batch, workers=SEED_WORKERS):
                if _cancel_flags.get(user_id):
                    cancelled = True
                    break
                checked += 1
                if err is not None:
                    error_count += 1
                elif res:
                    found_count += 1
                    try:
                        await safe_send(
                            context, chat_id, format_found_message(res[0], res[1])
                        )
                    except Exception:
                        logger.exception("notify")
                    try:
                        storage.mark_alerted("SEED", res[0])
                    except Exception:
                        pass
                else:
                    zero_count += 1

                now = time.monotonic()
                if checked == total or now - last_progress_at >= 5.0:
                    last_progress_at = now
                    elapsed = max(1, int(time.time() - _job_started_at.get(user_id, time.time())))
                    rate = checked / elapsed
                    eta = int((total - checked) / max(rate, 0.01))
                    await safe_edit(
                        status_msg,
                        f"📦 {batch_i + 1}/{n_batches}\n"
                        f"⏳ {checked:,}/{total:,} | 💰{found_count} | ⚪{zero_count} | ❌{error_count}\n"
                        f"⚡ ~{rate:.1f}/s | ETA ~{eta // 60}m",
                    )

            if cancelled:
                break

        tag = "🛑 Cancelado" if cancelled else "✅ Concluído"
        summary = (
            f"{tag}\n• {checked:,}/{total:,}\n• Com saldo: {found_count}\n"
            f"• Sem saldo: {zero_count}\n• Erros: {error_count}"
        )
        await safe_edit(status_msg, summary)
    except Exception as e:
        logger.exception("job failed")
        await safe_send(context, chat_id, f"❌ Erro no job: {type(e).__name__}: {e}\nUse /cancel")
    finally:
        _unlock(user_id)


async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if user_id in _running_checks:
        age = int(time.time() - _job_started_at[user_id]) if user_id in _job_started_at else -1
        # auto-libera se travado > 30 min
        if age > 1800:
            _unlock(user_id)
            await safe_send(context, chat_id, "⚠️ Job antigo liberado. Envie /check de novo.")
            return
        await safe_send(
            context,
            chat_id,
            "⏳ Em andamento" + (f" há {age}s" if age >= 0 else "") + ".\n/cancel para liberar.",
        )
        return

    pool = user_pools.get(user_id, [])
    if not pool:
        await safe_send(context, chat_id, "❌ Envie texto/.txt e /check.")
        return

    full_text = "\n".join(pool)
    if len(full_text) > MAX_FILE_CHARS:
        await safe_send(
            context,
            chat_id,
            f"❌ Entrada excede o limite configurado de {MAX_FILE_CHARS:,} caracteres.",
        )
        return
    user_pools[user_id] = []
    status_msg = await safe_send(context, chat_id, f"📥 {len(full_text):,} chars — iniciando...")

    _running_checks.add(user_id)

    async def _wrapper():
        try:
            await _run_check_job(context, chat_id, user_id, full_text, status_msg)
        except Exception:
            logger.exception("wrapper")
            _unlock(user_id)
            await safe_send(context, chat_id, "❌ Job caiu. /cancel e tente de novo.")

    try:
        context.application.create_task(_wrapper())
    except Exception as e:
        _unlock(user_id)
        await safe_edit(status_msg, f"❌ Não iniciou o job: {e}")


async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update) or not update.message:
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = ""
    if update.message.document:
        doc = update.message.document
        status = await safe_send(context, chat_id, "⏳ Baixando...")
        try:
            if doc.file_size and doc.file_size > MAX_FILE_CHARS:
                await safe_edit(
                    status,
                    f"❌ Arquivo excede o limite configurado de {MAX_FILE_CHARS:,} caracteres.",
                )
                return
            file = await context.bot.get_file(doc.file_id)
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                await file.download_to_drive(tmp.name)
                with open(tmp.name, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            if len(text) > MAX_FILE_CHARS:
                await safe_edit(
                    status,
                    f"❌ Conteúdo excede o limite configurado de {MAX_FILE_CHARS:,} caracteres.",
                )
                return
            await safe_edit(status, f"✅ {len(text):,} chars. /check")
        except Exception as e:
            await safe_edit(status, f"❌ {e}")
            return
    elif update.message.text:
        text = update.message.text
        await safe_send(context, chat_id, "📥 OK. /check")
    if text.strip():
        pool = user_pools.setdefault(user_id, [])
        current_chars = sum(len(item) for item in pool)
        if current_chars + len(text) > MAX_FILE_CHARS:
            await safe_send(
                context,
                chat_id,
                f"❌ O limite acumulado de {MAX_FILE_CHARS:,} caracteres por execução foi atingido. Use /check ou /clear.",
            )
            return
        pool.append(text)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, telegram.error.Conflict):
        logger.error("Conflict: outra instância com o mesmo token.")
        return
    logger.exception("update error", exc_info=context.error)


def build_app() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear_pool))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("check", check_pool))
    app.add_handler(CommandHandler("test", test_cmd))
    app.add_handler(
        MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, handle_input)
    )
    app.add_error_handler(error_handler)
    return app


def main():
    application = build_app()
    if RAILWAY_DOMAIN:
        url = f"https://{RAILWAY_DOMAIN}/{WEBHOOK_PATH}"
        logger.info(f"WEBHOOK {url} workers={SEED_WORKERS}")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=url,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("POLLING")

        async def _clear(app: Application):
            await app.bot.delete_webhook(drop_pending_updates=True)

        application.post_init = _clear
        application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("fatal")
