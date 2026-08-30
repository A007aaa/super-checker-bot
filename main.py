import os
import hashlib
import logging
import asyncio
import tempfile
import secrets
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_balance_master, preview_addresses, check_seeds_bulk
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

TELEGRAM_MAX_CHARS = 4096
# quantas seeds processar em paralelo dentro de um lote
SEED_WORKERS = max(1, int(os.getenv("SEED_WORKERS", "25")))
# tamanho do lote (pedido: 500)
BATCH_SIZE = max(1, int(os.getenv("BATCH_SIZE", "500"))
)
# limite Telegram bot API ~20MB; alertamos acima disso
MAX_FILE_CHARS = int(os.getenv("MAX_FILE_CHARS", str(15_000_000)))

RAILWAY_DOMAIN = (os.getenv("RAILWAY_PUBLIC_DOMAIN") or "").strip().rstrip(";")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", f"telegram/{secrets.token_hex(8)}")
PORT = int(os.getenv("PORT", "8080"))

NETWORK_LABELS = {
    "BTC": "Bitcoin (BTC)",
    "ETH": "Ethereum (ETH)",
    "USDT_ETH": "USDT (Ethereum ERC-20)",
    "SOL": "Solana (SOL)",
    "TRX": "Tron (TRX)",
    "USDT_TRX": "USDT (Tron TRC-20)",
    "USDC_TRX": "USDC (Tron TRC-20)",
}

TEST_SEED = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)


def format_seed_display(value: str) -> str:
    h = hashlib.sha256(value.encode()).hexdigest()[:16]
    words = value.split()
    if len(words) > 6:
        preview = " ".join(words[:3]) + " ... " + " ".join(words[-3:])
    else:
        preview = value
    return f"SEED (Hash: {h})\n{preview}"


def format_found_message(value: str, balances: list) -> str:
    lines = []
    for coin, addr, bal in balances:
        label = NETWORK_LABELS.get(coin, coin)
        lines.append(f"• {label}\n  Saldo: {bal}\n  `{addr}`")
    msg = (
        f"🎯 SALDO ENCONTRADO!\n\n"
        f"{format_seed_display(value)}\n\n"
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


async def safe_send(context, chat_id: int, text: str):
    try:
        return await context.bot.send_message(chat_id=chat_id, text=text)
    except telegram.error.RetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            return await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            return None
    except Exception as e:
        logger.exception(f"send: {e}")
        return None


async def safe_edit(message, text: str):
    if message is None:
        return None
    try:
        return await message.edit_text(text)
    except telegram.error.RetryAfter as e:
        if e.retry_after > 60:
            return message
        await asyncio.sleep(e.retry_after)
        try:
            return await message.edit_text(text)
        except Exception:
            return message
    except Exception:
        return message


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    await safe_send(
        context,
        update.effective_chat.id,
        "🚀 Super Checker Bot — modo bulk\n\n"
        "• Arquivos .txt grandes OK\n"
        f"• Lotes de até {BATCH_SIZE} seeds\n"
        f"• {SEED_WORKERS} workers em paralelo\n"
        "• Redes: BTC · ETH · USDT-ERC20 · SOL · TRX · USDT-TRC20\n\n"
        "Fluxo: envie texto/.txt → /check\n"
        "Comandos: /start /check /clear /test",
    )


async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    user_pools[update.effective_user.id] = []
    await safe_send(context, update.effective_chat.id, "🗑️ Memória limpa.")


async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    chat_id = update.effective_chat.id
    status = await safe_send(context, chat_id, "🧪 Testando todas as redes...")
    try:
        res = await check_balance_master("SEED", TEST_SEED)
        if res:
            _v, balances = res
            await safe_edit(
                status, "✅ Checker OK!\n\n" + format_found_message(TEST_SEED, balances)
            )
        else:
            await safe_edit(status, "⚠️ Sem saldo na seed de teste (RPC?).")
    except Exception as e:
        logger.exception("test failed")
        await safe_edit(status, f"❌ {e}")


async def _run_check_job(context, chat_id: int, user_id: int, full_text: str, status_msg):
    try:
        await safe_edit(status_msg, "🔍 Extraindo seeds BIP39 do texto/arquivo...")
        extractor = SeedExtractor()
        stats = await asyncio.to_thread(extractor.extract_with_stats, full_text)
        seeds = stats.valid

        if not seeds:
            extra = ""
            if stats.failed_checksum:
                sample = stats.failed_checksum[0].split()
                prev = " ".join(sample[:3]) + " ... " + " ".join(sample[-3:])
                extra = (
                    f"\n\n⚠️ {len(stats.failed_checksum)} frases com checksum inválido\n"
                    f"Ex.: {prev}"
                )
            await safe_edit(
                status_msg,
                f"⚠️ Nenhuma seed BIP39 válida.\n"
                f"Palavras: {stats.total_words} | Janelas: {stats.windows_scanned}"
                f"{extra}",
            )
            return

        total = len(seeds)
        n_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        await safe_edit(
            status_msg,
            f"✅ {total} seed(s) BIP39 válida(s)\n"
            f"📦 {n_batches} lote(s) de até {BATCH_SIZE}\n"
            f"⚙️ {SEED_WORKERS} workers | redes: BTC ETH SOL TRX\n"
            f"🔄 Iniciando...",
        )

        found_count = 0
        zero_count = 0
        error_count = 0
        checked = 0
        zero_samples: list[str] = []

        for batch_i in range(n_batches):
            start = batch_i * BATCH_SIZE
            batch = seeds[start : start + BATCH_SIZE]
            await safe_edit(
                status_msg,
                f"📦 Lote {batch_i + 1}/{n_batches} "
                f"({len(batch)} seeds)\n"
                f"⏳ Total: {checked}/{total} | 💰{found_count} | ⚪{zero_count} | ❌{error_count}",
            )

            async for seed, res, err in check_seeds_bulk(batch, workers=SEED_WORKERS):
                checked += 1
                if err is not None:
                    error_count += 1
                elif res:
                    _v, balances = res
                    found_count += 1
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=format_found_message(_v, balances),
                        )
                    except telegram.error.RetryAfter as e:
                        await asyncio.sleep(e.retry_after)
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=format_found_message(_v, balances),
                        )
                    except Exception:
                        logger.exception("falha ao notificar saldo")
                    try:
                        storage.mark_alerted("SEED", _v)
                    except Exception:
                        pass
                else:
                    zero_count += 1
                    if len(zero_samples) < 5:
                        try:
                            addrs = preview_addresses(seed)
                            w = seed.split()
                            prev = " ".join(w[:2]) + "…" + " ".join(w[-2:])
                            zero_samples.append(
                                f"• {prev}\n  TRX `{addrs.get('trx', '?')}`"
                            )
                        except Exception:
                            pass

                if checked % 10 == 0 or checked == total:
                    await safe_edit(
                        status_msg,
                        f"📦 Lote {batch_i + 1}/{n_batches}\n"
                        f"⏳ {checked}/{total} | 💰{found_count} | ⚪{zero_count} | ❌{error_count}",
                    )

        summary = (
            f"✅ Concluído\n"
            f"• Seeds BIP39: {total}\n"
            f"• Lotes: {n_batches} × até {BATCH_SIZE}\n"
            f"• Com saldo: {found_count}\n"
            f"• Sem saldo: {zero_count}\n"
            f"• Erros: {error_count}\n\n"
            f"Redes: BTC · ETH+USDT · SOL · TRX+TRC20"
        )
        if zero_samples and found_count == 0:
            summary += (
                "\n\n🔎 Amostra TRX path0 (sem saldo):\n"
                + "\n".join(zero_samples)
                + "\n\nSe o endereço no Tronscan for outro → path/passphrase diferente."
            )
        await safe_edit(status_msg, summary)
        await safe_send(context, chat_id, summary)

    except Exception:
        logger.exception("job failed")
        await safe_send(context, chat_id, "❌ Erro interno no check. Veja logs no Railway.")
    finally:
        _running_checks.discard(user_id)


async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if user_id in _running_checks:
        await safe_send(
            context, chat_id, "⏳ Já há um /check em andamento. Aguarde terminar."
        )
        return

    pool = user_pools.get(user_id, [])
    if not pool:
        await safe_send(
            context, chat_id, "❌ Nada na memória. Envie texto ou .txt e use /check."
        )
        return

    full_text = "\n".join(pool)
    user_pools[user_id] = []

    status_msg = await safe_send(
        context,
        chat_id,
        f"📥 Recebido: {len(full_text):,} caracteres\n"
        f"Background job iniciado (webhook liberado)...",
    )

    _running_checks.add(user_id)
    context.application.create_task(
        _run_check_job(context, chat_id, user_id, full_text, status_msg)
    )


async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    if not update.message:
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = ""

    if update.message.document:
        doc = update.message.document
        status = await safe_send(context, chat_id, "⏳ Baixando arquivo...")
        try:
            if doc.file_size and doc.file_size > 20 * 1024 * 1024:
                await safe_edit(
                    status,
                    "❌ Arquivo > 20MB (limite do Telegram Bot API). Divida o .txt.",
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
                    f"⚠️ Arquivo muito grande ({len(text):,} chars). "
                    f"Usando os primeiros {MAX_FILE_CHARS:,}.",
                )
                text = text[:MAX_FILE_CHARS]
            else:
                await safe_edit(
                    status,
                    f"✅ Arquivo OK: {len(text):,} caracteres.\nUse /check",
                )
        except Exception as e:
            await safe_edit(status, f"❌ Erro ao ler arquivo: {e}")
            return
    elif update.message.text:
        text = update.message.text
        await safe_send(context, chat_id, "📥 Texto adicionado. Use /check")

    if text.strip():
        user_pools.setdefault(user_id, []).append(text)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, telegram.error.Conflict):
        logger.error("Conflict: outra instância com este token.")
        return
    logger.exception("update error", exc_info=err)


def build_app() -> Application:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("clear", clear_pool))
    application.add_handler(CommandHandler("check", check_pool))
    application.add_handler(CommandHandler("test", test_cmd))
    application.add_handler(
        MessageHandler(
            (filters.TEXT | filters.Document.ALL) & ~filters.COMMAND,
            handle_input,
        )
    )
    application.add_error_handler(error_handler)
    return application


def main():
    application = build_app()
    if RAILWAY_DOMAIN:
        webhook_url = f"https://{RAILWAY_DOMAIN}/{WEBHOOK_PATH}"
        logger.info(f"WEBHOOK {webhook_url} | batch={BATCH_SIZE} workers={SEED_WORKERS}")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=webhook_url,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("POLLING mode")

        async def _clear(app: Application):
            await app.bot.delete_webhook(drop_pending_updates=True)

        application.post_init = _clear
        application.run_polling(
            drop_pending_updates=True, allowed_updates=Update.ALL_TYPES
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("fatal")
