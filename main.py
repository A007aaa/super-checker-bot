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
from blockchain_checker import check_balance_master, preview_addresses
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
# evita dois /check simultâneos no mesmo usuário
_running_checks: set[int] = set()

TELEGRAM_MAX_CHARS = 4096
SEED_WORKERS = max(1, int(os.getenv("SEED_WORKERS", "10")))

RAILWAY_DOMAIN = (os.getenv("RAILWAY_PUBLIC_DOMAIN") or "").strip().rstrip(";")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", f"telegram/{secrets.token_hex(8)}")
PORT = int(os.getenv("PORT", "8080"))

NETWORK_LABELS = {
    "BTC": "Bitcoin (BTC)",
    "ETH": "Ethereum (ETH)",
    "USDT_ETH": "Tether USDT (Ethereum ERC-20)",
    "SOL": "Solana (SOL)",
    "TRX": "Tron (TRX)",
    "USDT_TRX": "Tether USDT (Tron TRC-20)",
    "USDC_TRX": "USD Coin (Tron TRC-20)",
}

TEST_SEED = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)


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
    return f"{item_type}\n{value}"


def format_found_message(item_type: str, value: str, balances: list) -> str:
    seed_line = format_seed_display(item_type, value, show_full=False)
    lines = []
    for coin, addr, bal in balances:
        label = NETWORK_LABELS.get(coin, coin)
        lines.append(f"• {label}\n  Saldo: {bal}\n  Endereço: `{addr}`")
    balance_block = "\n\n".join(lines)
    msg = (
        f"🎯 SALDO ENCONTRADO!\n\n"
        f"{seed_line}\n\n"
        f"💰 Redes com saldo:\n\n"
        f"{balance_block}"
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
    chat_id: int | None = None,
):
    try:
        if update and getattr(update, "message", None):
            return await update.message.reply_text(text)
        cid = chat_id
        if cid is None and update and getattr(update, "effective_chat", None):
            cid = update.effective_chat.id
        if context and cid is not None:
            return await context.bot.send_message(chat_id=cid, text=text)
    except telegram.error.RetryAfter as e:
        await asyncio.sleep(e.retry_after)
        return await safe_send_message(update, text, context, chat_id)
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
        "🚀 Super Checker Bot pronto!\n\n"
        "1) Envie texto ou .txt\n"
        "2) Use /check\n\n"
        "Prioridade: TRON (TRX + TRC-20 USDT)\n"
        "Também: BTC · ETH · SOL\n"
        "Comandos: /start /check /clear /test",
        context,
    )


async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    user_pools[update.effective_user.id] = []
    await safe_send_message(update, "🗑️ Memória limpa.", context)


async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    status = await safe_send_message(
        update, "🧪 Testando checker (seed pública BIP39)...", context
    )
    try:
        res = await check_balance_master("SEED", TEST_SEED)
        if res:
            _v, balances = res
            await safe_edit_message(
                status,
                "✅ Checker OK!\n\n"
                + format_found_message("SEED", TEST_SEED, balances),
            )
        else:
            await safe_edit_message(
                status, "⚠️ Checker rodou sem saldo na seed de teste (RPC?)."
            )
    except Exception as e:
        logger.exception("test_cmd failed")
        await safe_edit_message(status, f"❌ Erro no teste: {e}")


async def _run_check_job(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    full_text: str,
    status_msg,
):
    """Trabalho pesado fora do handler do webhook (evita timeout do Telegram)."""
    try:
        extractor = SeedExtractor()
        stats = await asyncio.to_thread(extractor.extract_with_stats, full_text)
        seeds = stats.valid

        if not seeds:
            fail_n = len(stats.failed_checksum)
            extra = ""
            if fail_n:
                sample = stats.failed_checksum[0].split()
                preview = " ".join(sample[:3]) + " ... " + " ".join(sample[-3:])
                extra = (
                    f"\n\n⚠️ {fail_n} frase(s) com palavras BIP39 mas checksum INVÁLIDO.\n"
                    f"Ex.: {preview}\n"
                    f"Não é seed BIP39 válida (palavra errada / Electrum / outra wordlist)."
                )
            await safe_edit_message(
                status_msg,
                f"⚠️ Nenhuma seed BIP39 válida.\n"
                f"Palavras: {stats.total_words} | Janelas: {stats.windows_scanned}"
                f"{extra}",
            )
            return

        total = len(seeds)
        diag = f"✅ {total} seed(s) BIP39 válida(s)"
        if stats.failed_checksum:
            diag += f"\n⚠️ {len(stats.failed_checksum)} checksum inválido (ignoradas)"
        await safe_edit_message(
            status_msg,
            diag + "\n🔄 Checando TRON/TRC-20 prioritário (em background)...",
        )

        sem = asyncio.Semaphore(SEED_WORKERS)
        found_count = 0
        zero_count = 0
        error_count = 0
        checked = 0
        zero_samples: list[str] = []
        lock = asyncio.Lock()

        async def process_one(seed: str):
            nonlocal found_count, zero_count, error_count, checked
            async with sem:
                try:
                    res = await check_balance_master("SEED", seed)
                    if res:
                        v, balances = res
                        msg = format_found_message("SEED", v, balances)
                        await context.bot.send_message(chat_id=chat_id, text=msg)
                        try:
                            storage.mark_alerted("SEED", v)
                        except Exception:
                            pass
                        async with lock:
                            found_count += 1
                    else:
                        async with lock:
                            zero_count += 1
                            if len(zero_samples) < 5:
                                try:
                                    addrs = preview_addresses(seed)
                                    words = seed.split()
                                    prev = (
                                        " ".join(words[:2])
                                        + "…"
                                        + " ".join(words[-2:])
                                    )
                                    zero_samples.append(
                                        f"• {prev}\n"
                                        f"  TRX `{addrs.get('trx', '?')}`\n"
                                        f"  ETH `{addrs.get('eth', '?')}`"
                                    )
                                except Exception:
                                    pass
                except Exception as e:
                    logger.exception(f"Erro seed: {e}")
                    async with lock:
                        error_count += 1
                finally:
                    async with lock:
                        checked += 1
                        if checked % 3 == 0 or checked == total:
                            await safe_edit_message(
                                status_msg,
                                f"⏳ {checked}/{total} | 💰{found_count} | ⚪{zero_count} | ❌{error_count}",
                            )

        await asyncio.gather(*(process_one(s) for s in seeds))

        summary = (
            f"✅ Concluído\n"
            f"• Seeds BIP39 válidas: {total}\n"
            f"• Com saldo: {found_count}\n"
            f"• Sem saldo (path padrão): {zero_count}\n"
            f"• Erros: {error_count}"
        )
        if zero_samples:
            summary += (
                "\n\n🔎 TRX path0 das seeds sem saldo:\n"
                + "\n".join(zero_samples)
                + "\n\nAbra o TRX no tronscan.org e compare com a carteira.\n"
                "Se for outro endereço = path/passphrase diferente."
            )
        await safe_edit_message(status_msg, summary)
    except Exception:
        logger.exception("_run_check_job failed")
        try:
            await context.bot.send_message(
                chat_id=chat_id, text="❌ Erro interno durante o check. Veja os logs."
            )
        except Exception:
            pass
    finally:
        _running_checks.discard(user_id)


async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if user_id in _running_checks:
        await safe_send_message(
            update, "⏳ Já existe um /check em andamento. Aguarde terminar.", context
        )
        return

    pool = user_pools.get(user_id, [])
    if not pool:
        await safe_send_message(
            update, "❌ Nada para verificar. Envie texto ou .txt primeiro.", context
        )
        return

    full_text = " ".join(pool)
    # limpa pool já — job usa a cópia full_text
    user_pools[user_id] = []

    status_msg = await safe_send_message(
        update,
        f"🔍 Recebido ({len(full_text)} caracteres).\n"
        f"Processando em background (webhook não trava)...",
        context,
    )

    _running_checks.add(user_id)
    # importa: não await — libera o webhook imediatamente
    context.application.create_task(
        _run_check_job(context, chat_id, user_id, full_text, status_msg)
    )


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
                status, f"✅ Arquivo de {len(text)} caracteres. Use /check"
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
