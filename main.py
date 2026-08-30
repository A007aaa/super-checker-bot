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
SEED_WORKERS = max(1, int(os.getenv("SEED_WORKERS", "50")))
BATCH_SIZE = max(1, int(os.getenv("BATCH_SIZE", "500")))
MAX_FILE_CHARS = int(os.getenv("MAX_FILE_CHARS", str(15_000_000)))

RAILWAY_DOMAIN = (os.getenv("RAILWAY_PUBLIC_DOMAIN") or "").strip().rstrip(";")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", f"telegram/{secrets.token_hex(8)}")
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
        "🚀 Super Checker — modo RÁPIDO\n\n"
        f"• Lotes de {BATCH_SIZE} seeds\n"
        f"• {SEED_WORKERS} workers paralelos\n"
        "• Path padrão (account0 / idx 0–2)\n"
        "• Redes: BTC ETH BSC Polygon SOL TRX + USDT\n\n"
        "Envie .txt → /check\n"
        "/start /check /clear /test",
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
    status = await safe_send(context, chat_id, "🧪 Teste rápido...")
    try:
        res = await check_balance_master("SEED", TEST_SEED)
        if res:
            _v, balances = res
            await safe_edit(
                status, "✅ OK!\n\n" + format_found_message(TEST_SEED, balances)
            )
        else:
            await safe_edit(status, "⚠️ Sem saldo na seed de teste.")
    except Exception as e:
        logger.exception("test failed")
        await safe_edit(status, f"❌ {e}")


async def _run_check_job(context, chat_id: int, user_id: int, full_text: str, status_msg):
    try:
        await safe_edit(status_msg, "🔍 Extraindo seeds BIP39...")
        extractor = SeedExtractor()
        stats = await asyncio.to_thread(extractor.extract_with_stats, full_text)
        seeds = stats.valid

        if not seeds:
            extra = ""
            if stats.failed_checksum:
                sample = stats.failed_checksum[0].split()
                prev = " ".join(sample[:3]) + " ... " + " ".join(sample[-3:])
                extra = f"\n\n⚠️ {len(stats.failed_checksum)} checksum inválido\nEx.: {prev}"
            await safe_edit(
                status_msg,
                f"⚠️ Nenhuma seed BIP39 válida.\n"
                f"Palavras: {stats.total_words}"
                f"{extra}",
            )
            return

        total = len(seeds)
        n_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        await safe_edit(
            status_msg,
            f"✅ {total} seeds | {n_batches} lote(s)×{BATCH_SIZE}\n"
            f"⚡ {SEED_WORKERS} workers | modo rápido\n"
            f"🔄 Iniciando...",
        )

        found_count = 0
        zero_count = 0
        error_count = 0
        checked = 0
        zero_samples: list[str] = []
        last_edit = 0.0

        for batch_i in range(n_batches):
            start = batch_i * BATCH_SIZE
            batch = seeds[start : start + BATCH_SIZE]

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
                        try:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=format_found_message(_v, balances),
                            )
                        except Exception:
                            pass
                    except Exception:
                        logger.exception("notify fail")
                    try:
                        storage.mark_alerted("SEED", _v)
                    except Exception:
                        pass
                else:
                    zero_count += 1
                    if len(zero_samples) < 3:
                        try:
                            addrs = preview_addresses(seed)
                            w = seed.split()
                            prev = " ".join(w[:2]) + "…" + " ".join(w[-2:])
                            zero_samples.append(f"• {prev}\n  TRX `{addrs.get('trx', '?')}`")
                        except Exception:
                            pass

                # atualiza status a cada 25 seeds (menos flood / mais velocidade)
                if checked % 25 == 0 or checked == total:
                    await safe_edit(
                        status_msg,
                        f"📦 Lote {batch_i + 1}/{n_batches}\n"
                        f"⏳ {checked}/{total} | 💰{found_count} | ⚪{zero_count} | ❌{error_count}",
                    )

        summary = (
            f"✅ Concluído\n"
            f"• Seeds: {total}\n"
            f"• Com saldo: {found_count}\n"
            f"• Sem saldo: {zero_count}\n"
            f"• Erros: {error_count}"
        )
        if zero_samples and found_count == 0:
            summary += "\n\n🔎 Amostra TRX:\n" + "\n".join(zero_samples)
        await safe_edit(status_msg, summary)
        await safe_send(context, chat_id, summary)

    except Exception:
        logger.exception("job failed")
        await safe_send(context, chat_id, "❌ Erro interno. Veja logs.")
    finally:
        _running_checks.discard(user_id)


async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if user_id in _running_checks:
        await safe_send(context, chat_id, "⏳ Check em andamento. Aguarde.")
        return

    pool = user_pools.get(user_id, [])
    if not pool:
        await safe_send(context, chat_id, "❌ Envie texto/.txt e use /check.")
        return

    full_text = "\n".join(pool)
    user_pools[user_id] = []

    status_msg = await safe_send(
        context,
        chat_id,
        f"📥 {len(full_text):,} chars — job iniciado...",
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
                await safe_edit(status, "❌ Arquivo > 20MB. Divida o .txt.")
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
                text = text[:MAX_FILE_CHARS]
                await safe_edit(status, f"⚠️ Truncado para {MAX_FILE_CHARS:,} chars. /check")
            else:
                await safe_edit(status, f"✅ {len(text):,} chars. Use /check")
        except Exception as e:
            await safe_edit(status, f"❌ {e}")
            return
    elif update.message.text:
        text = update.message.text
        await safe_send(context, chat_id, "📥 OK. Use /check")

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
        logger.info(f"WEBHOOK fast | workers={SEED_WORKERS} batch={BATCH_SIZE}")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=webhook_url,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("POLLING")

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
