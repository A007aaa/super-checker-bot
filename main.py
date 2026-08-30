import os
import hashlib
import logging
import asyncio
import tempfile
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_balance_master
from tools.seed_extractor import SeedExtractor
import storage
import telegram.error

# Configuração de Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO)
)
logger = logging.getLogger(__name__)

# Configurações do Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8785377732:AAFDwUBm7rDkFa_ZMSk0szz2L3DzQUqBiY8")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "8422682029"))

# initialize storage (SQLite) for persisted alerts
try:
    storage.init_db()
except Exception as e:
    logger.error(f"Failed to initialize storage: {e}")

user_pools = {}

TELEGRAM_MAX_CHARS = 4096


def format_seed_display(item_type: str, value: str, show_full: bool = False) -> str:
    """
    Formata a exibição de seeds/chaves/endereços de forma segura e compacta.
    """
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

    # Endereços diretos — exibir completo
    return f"{item_type}\n{value}"


def format_found_message(item_type: str, value: str, balances: list) -> str:
    """
    Monta a mensagem de saldo encontrado com estrutura clara e emojis.
    Por segurança, não expõe a seed completa por padrão.
    """
    seed_line = format_seed_display(item_type, value, show_full=False)

    balance_lines = "\n".join(
        f"• {coin}: {bal}" for coin, _addr, bal in balances
    )

    msg = (
        f"🎯 SALDO ENCONTRADO!\n\n"
        f"{seed_line}\n\n"
        f"💰 Saldos encontrados:\n"
        f"{balance_lines}"
    )

    if len(msg) > TELEGRAM_MAX_CHARS:
        msg = msg[: TELEGRAM_MAX_CHARS - 3] + "..."

    return msg


async def is_authorized(update: Update) -> bool:
    if not update or not update.effective_user:
        return False
    return update.effective_user.id == ALLOWED_USER_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    await safe_send_message(update, "🚀 **BOT ATUALIZADO!**\nEnvie seus arquivos .txt e use /check.", context)


async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    user_pools[update.effective_user.id] = []
    await safe_send_message(update, "🗑️ Memória limpa.", context)


async def safe_send_message(update: Update | None, text: str, context: ContextTypes.DEFAULT_TYPE | None = None):
    """Envia mensagem com tratamento de Flood Control. Usa update.message ou context as fallback."""
    try:
        if update and getattr(update, "message", None):
            return await update.message.reply_text(text)
        if context and getattr(update, "effective_chat", None):
            return await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
        logger.error("safe_send_message: sem meio de enviar mensagem (update.message e context faltando)")
    except telegram.error.RetryAfter as e:
        logger.warning(f"Flood control atingido. Aguardando {e.retry_after} segundos...")
        await asyncio.sleep(e.retry_after)
        if update and getattr(update, "message", None):
            return await update.message.reply_text(text)
    except Exception as e:
        logger.exception(f"Erro ao enviar mensagem: {e}")


async def safe_edit_message(message, text: str, context: ContextTypes.DEFAULT_TYPE | None = None):
    """Edita mensagem com tratamento de Flood Control; retorna a message (ou a original)."""
    if message is None:
        return None
    try:
        return await message.edit_text(text)
    except telegram.error.RetryAfter as e:
        if e.retry_after > 60:
            logger.error(f"Flood control excessivo ({e.retry_after}s). Pulando edição de status.")
            return message
        logger.warning(f"Flood control na edição. Aguardando {e.retry_after}s...")
        await asyncio.sleep(e.retry_after)
        try:
            return await message.edit_text(text)
        except Exception:
            logger.exception("Falha na segunda tentativa de edit_text")
            return message
    except Exception as e:
        logger.exception(f"Erro ao editar mensagem: {e}")
        return message


# --- New streaming check_pool using producer(queue)/workers to avoid blocking ---
SEED_WORKERS = int(os.getenv("SEED_WORKERS", "6"))

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    user_id = update.effective_user.id
    pool = user_pools.get(user_id, [])
    if not pool:
        await safe_send_message(update, "❌ Nada para verificar.", context)
        return

    # concatenação conforme solicitado pelo usuário
    full_text = " ".join(pool)
    total_chars = len(full_text)
    logger.info(f"🔍 Iniciando extração — texto com {total_chars} caracteres")
    status_msg = await safe_send_message(update, f"🔍 Extraindo itens do texto acumulado ({total_chars} caracteres)... Aguarde.", context)

    # safeguard: warn if extremely large
    MAX_CHARS = int(os.getenv("MAX_POOL_CHARS", str(20_000_000)))
    if total_chars > MAX_CHARS:
        await safe_edit_message(status_msg, f"⚠️ Texto muito grande ({total_chars} chars). Processo será executado, mas pode demorar. Use arquivos para eficiência.", context)

    # prepare extractor and queue
    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    extractor = SeedExtractor()  # uses default chunk_size/overlap
    loop = asyncio.get_running_loop()

    # producer runs in thread and pushes seeds to the asyncio queue
    def producer():
        try:
            for seed in extractor.extract_all_iter(full_text):
                asyncio.run_coroutine_threadsafe(queue.put(seed), loop).result()
        finally:
            # sentinel to signal end to workers
            asyncio.run_coroutine_threadsafe(queue.put(None), loop).result()

    prod_task = asyncio.to_thread(producer)

    # worker consumes seeds and runs checks
    async def worker(worker_id: int):
        async with asyncio.Semaphore(1):
            while True:
                seed = await queue.get()
                if seed is None:
                    # propagate sentinel and exit
                    await queue.put(None)
                    queue.task_done()
                    break
                try:
                    res = await check_balance_master("SEED", seed)
                    if res:
                        v, balances = res
                        try:
                            already = storage.is_alerted("SEED", v)
                        except Exception as e:
                            logger.exception(f"Storage check error: {e}")
                            already = False

                        if not already:
                            msg = format_found_message("SEED", v, balances)
                            await safe_send_message(update, msg, context)
                            try:
                                storage.mark_alerted("SEED", v)
                            except Exception:
                                logger.exception("Erro ao marcar alert no storage")
                except Exception as e:
                    logger.exception(f"Worker {worker_id} erro ao processar seed: {e}")
                finally:
                    queue.task_done()

    # start workers
    workers = [asyncio.create_task(worker(i)) for i in range(SEED_WORKERS)]

    # wait for producer and processing to finish
    await prod_task
    await queue.join()

    # cancel workers
    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)

    await safe_edit_message(status_msg, f"✅ Extração e varredura concluídas. Itens verificados e alertas enviados.", context)
    # clear user pool
    user_pools[user_id] = []


async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    user_id = update.effective_user.id
    text = ""

    if update.message.document:
        status = await safe_send_message(update, "⏳ Lendo arquivo... Isso pode levar alguns segundos.", context)
        try:
            file = await context.bot.get_file(update.message.document.file_id)
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                await file.download_to_drive(tmp.name)
                # read into memory (kept as requested); for very large files consider changing
                with open(tmp.name, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
            os.unlink(tmp.name)
            await safe_edit_message(status, f"✅ Arquivo de {len(text)} caracteres lido com sucesso. Use /check para processar.", context)
        except Exception as e:
            await safe_edit_message(status, f"❌ Erro ao ler arquivo: {e}", context)
            return
    elif update.message.text:
        text = update.message.text
        await safe_send_message(update, "📥 Texto adicionado. Use /check", context)

    if text.strip():
        if user_id not in user_pools:
            user_pools[user_id] = []
        user_pools[user_id].append(text)


def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("clear", clear_pool))
    application.add_handler(CommandHandler("check", check_pool))
    application.add_handler(MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, handle_input))

    # run with the higher-level run_polling API
    try:
        application.run_polling(drop_pending_updates=True)
    except telegram.error.Conflict:
        # Friendly exit to avoid noisy tracebacks when another instance or webhook exists
        logger.error("Conflict detected: another getUpdates process or webhook is active. Exiting cleanly.")
        try:
            application.stop()
        except Exception:
            pass
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Unhandled exception in main loop")
