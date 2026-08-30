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
from blockchain_checker import check_balance_master
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
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN não definido. Configure a variável de ambiente."
    )

_allowed_raw = os.getenv("ALLOWED_USER_ID", "0").strip() or "0"
try:
    ALLOWED_USER_ID = int(_allowed_raw)
except ValueError:
    ALLOWED_USER_ID = 0
    logger.warning("ALLOWED_USER_ID inválido; usando 0 (sem restrição)")

try:
    storage.init_db()
except Exception as e:
    logger.error(f"Failed to initialize storage: {e}")

user_pools: dict[int, list[str]] = {}

TELEGRAM_MAX_CHARS = 4096
# quantas seeds processar em paralelo
SEED_WORKERS = max(1, int(os.getenv("SEED_WORKERS", "25")))

RAILWAY_DOMAIN = (os.getenv("RAILWAY_PUBLIC_DOMAIN") or "").strip().rstrip(";")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", f"telegram/{secrets.token_hex(8)}")
PORT = int(os.getenv("PORT", "8080"))


def format_seed_display(item_type: str, value: str, show_full: bool = False) -> str:
    if item_type == "SEED":
        if show_full:
            return f"SEED:\n{value}"
        sha256_hash = hashlib.sha256(value.encode()).hexdigest()[:16]
        words = value.split()
        if len(words) > 6:
            preview = " ".join(words[:3]) + " ... " + " ".join(words[-3:])
        else:
            preview = value
        return f"SEED (Hash: {sha256_hash})\n{preview}"

    if item_type in ("KEY_SOL", "KEY_HEX"):
        truncated = value[:10] + "..." + value[-10:] if len(value) > 20 else value
        return f"{item_type}\n{truncated}"

    return f"{item_type}\n{value}"


def format_found_message(item_type: str, value: str, balances: list) -> str:
    seed_line = format_seed_display(item_type, value, show_full=False)
    balance_lines = "\n".join(
        f"• {coin}: {bal}\n  `{addr}`" for coin, addr, bal in balances
    )
    msg = (
        f"🎯 SALDO ENCONTRADO!\n\n"
        f"{seed_line}\n\n"
        f"💰 Saldos:\n"
        f"{balance_lines}"
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


async def safe_send_message(
    update: Update | None,
    text: str,
    context: ContextTypes.DEFAULT_TYPE | None = None,
):
    try:
        if update and getattr(update, "message", None):
            return await update.message.reply_text(text)
        if context and update and getattr(update, "effective_chat", None):
            return await context.bot.send_message(
                chat_id=update.effective_chat.id, text=text
            )
        logger.error("safe_send_message: sem meio de enviar mensagem")
    except telegram.error.RetryAfter as e:
        logger.warning(f"Flood control. Aguardando {e.retry_after}s...")
        await asyncio.sleep(e.retry_after)
        if update and getattr(update, "message", None):
            return await update.message.reply_text(text)
    except Exception as e:
        logger.exception(f"Erro ao enviar mensagem: {e}")
    return None


async def safe_edit_message(message, text: str):
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
    await safe_send_message(
        update,
        "🚀 Super Checker Bot pronto!\n"
        "Envie texto/arquivo .txt e use /check.\n"
        "Cadeias: BTC, ETH+USDT, SOL, TRX+USDT.\n"
        f"Paralelo: {SEED_WORKERS} seeds | ~500 paths/seed.\n"
        "Comandos: /start /check /clear",
        context,
    )


async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    user_pools[update.effective_user.id] = []
    await safe_send_message(update, "🗑️ Memória limpa.", context)


async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return

    user_id = update.effective_user.id
    pool = user_pools.get(user_id, [])
    if not pool:
        await safe_send_message(
            update, "❌ Nada para verificar. Envie texto ou .txt primeiro.", context
        )
        return

    full_text = " ".join(pool)
    total_chars = len(full_text)
    logger.info(f"🔍 Extração — {total_chars} chars")
    status_msg = await safe_send_message(
        update,
        f"🔍 Extraindo seeds ({total_chars} caracteres)...",
        context,
    )

    extractor = SeedExtractor()
    try:
        seeds = await asyncio.to_thread(extractor.extract_all, full_text)
    except Exception as e:
        logger.exception("Falha na extração")
        await safe_edit_message(status_msg, f"❌ Erro na extração: {e}")
        return

    if not seeds:
        await safe_edit_message(
            status_msg,
            "⚠️ Nenhuma seed BIP39 válida encontrada.\n"
            "Precisa de 12/15/18/21/24 palavras com checksum correto.\n"
            "Se as palavras estiverem certas mas o checksum falhar, a seed é inválida.",
        )
        user_pools[user_id] = []
        return

    total = len(seeds)
    logger.info(f"✅ {total} seed(s) válida(s) — workers={SEED_WORKERS}")
    await safe_edit_message(
        status_msg,
        f"✅ {total} seed(s) válida(s).\n"
        f"Workers: {SEED_WORKERS} | ~500 paths/seed\n"
        f"Verificando BTC/ETH/SOL/TRX...",
    )

    sem = asyncio.Semaphore(SEED_WORKERS)
    found_count = 0
    zero_count = 0
    error_count = 0
    checked = 0
    lock = asyncio.Lock()

    async def process_one(seed: str):
        nonlocal found_count, zero_count, error_count, checked
        async with sem:
            try:
                res = await check_balance_master("SEED", seed)
                if res:
                    v, balances = res
                    msg = format_found_message("SEED", v, balances)
                    await safe_send_message(update, msg, context)
                    try:
                        storage.mark_alerted("SEED", v)
                    except Exception:
                        pass
                    async with lock:
                        found_count += 1
                else:
                    async with lock:
                        zero_count += 1
            except Exception as e:
                logger.exception(f"Erro ao processar seed: {e}")
                async with lock:
                    error_count += 1
            finally:
                async with lock:
                    checked += 1
                    if checked % 10 == 0 or checked == total:
                        await safe_edit_message(
                            status_msg,
                            f"⏳ {checked}/{total} | 💰{found_count} | ⚪{zero_count} | ❌{error_count}",
                        )

    await asyncio.gather(*(process_one(s) for s in seeds))

    await safe_edit_message(
        status_msg,
        f"✅ Concluído\n"
        f"• Seeds válidas: {total}\n"
        f"• Com saldo: {found_count}\n"
        f"• Sem saldo (paths BIP44/84): {zero_count}\n"
        f"• Erros: {error_count}\n\n"
        f"Limite: BTC, ETH(+USDT), SOL, TRX(+USDT).",
    )
    user_pools[user_id] = []


async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    if not update.message:
        return

    user_id = update.effective_user.id
    text = ""

    if update.message.document:
        status = await safe_send_message(update, "⏳ Lendo arquivo...", context)
        try:
            file = await context.bot.get_file(update.message.document.file_id)
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                await file.download_to_drive(tmp.name)
                with open(tmp.name, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            await safe_edit_message(
                status,
                f"✅ Arquivo de {len(text)} caracteres. Use /check",
            )
        except Exception as e:
            await safe_edit_message(status, f"❌ Erro ao ler arquivo: {e}")
            return
    elif update.message.text:
        text = update.message.text
        await safe_send_message(update, "📥 Texto adicionado. Use /check", context)

    if text.strip():
        user_pools.setdefault(user_id, []).append(text)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, telegram.error.Conflict):
        logger.error("Conflict: outra instância usa este token.")
        return
    logger.exception("Exception while handling update", exc_info=err)


def build_app() -> Application:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("clear", clear_pool))
    application.add_handler(CommandHandler("check", check_pool))
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
        logger.info(f"Modo WEBHOOK: {webhook_url}")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=webhook_url,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("Modo POLLING (sem RAILWAY_PUBLIC_DOMAIN)")

        async def _clear_webhook(app: Application) -> None:
            await app.bot.delete_webhook(drop_pending_updates=True)
            logger.info("Webhook removido. Usando getUpdates.")

        application.post_init = _clear_webhook
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Unhandled exception in main loop")
