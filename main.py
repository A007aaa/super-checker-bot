import os
import hashlib
import logging
import asyncio
import tempfile
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_balance_master
from seed_extractor import SeedExtractor

# Configuração de Logging
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configurações do Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8785377732:AAFDwUBm7rDkFa_ZMSk0szz2L3DzQUqBiY8")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "8422682029"))

extractor = SeedExtractor()
user_pools = {}

TELEGRAM_MAX_CHARS = 4096


def format_seed_display(item_type: str, value: str, show_full: bool = False) -> str:
    """
    Formata a exibição de seeds/chaves/endereços de forma segura e compacta.

    - SEED (show_full=False): SHA256 (primeiros 16 chars) + primeiras 3 palavras + últimas 3 palavras
    - SEED (show_full=True): seed completa, sem truncamento
    - KEY_SOL / KEY_HEX: primeiros 10 + últimos 10 caracteres
    - Endereços diretos: valor completo
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
    Exibe a seed COMPLETA quando saldo é encontrado.
    Garante que o resultado não ultrapasse TELEGRAM_MAX_CHARS.
    """
    seed_line = format_seed_display(item_type, value, show_full=True)

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
    if not update or not update.effective_user: return False
    return update.effective_user.id == ALLOWED_USER_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update): return
    await update.message.reply_text("🚀 **BOT ATUALIZADO!**\nEnvie seus arquivos .txt e use /check.")

async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update): return
    user_pools[update.effective_user.id] = []
    await update.message.reply_text("🗑️ Memória limpa.")

import telegram.error

async def safe_send_message(update: Update, text: str):
    """Envia mensagem com tratamento de Flood Control."""
    try:
        return await update.message.reply_text(text)
    except telegram.error.RetryAfter as e:
        logger.warning(f"Flood control atingido. Aguardando {e.retry_after} segundos...")
        await asyncio.sleep(e.retry_after)
        return await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem: {e}")

async def safe_edit_message(message, text: str):
    """Edita mensagem com tratamento de Flood Control agressivo."""
    try:
        return await message.edit_text(text)
    except telegram.error.RetryAfter as e:
        # Se o tempo for muito longo (ex: > 60s), não travamos o bot, apenas logamos
        if e.retry_after > 60:
            logger.error(f"Flood control excessivo ({e.retry_after}s). Pulando edição de status.")
            return message
        logger.warning(f"Flood control na edição. Aguardando {e.retry_after}s...")
        await asyncio.sleep(e.retry_after)
        try:
            return await message.edit_text(text)
        except: return message
    except Exception as e:
        logger.error(f"Erro ao editar mensagem: {e}")
        return message

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update): return
    user_id = update.effective_user.id
    pool = user_pools.get(user_id, [])
    if not pool:
        await safe_send_message(update, "❌ Nada para verificar.")
        return

    full_text = " ".join(pool)
    total_chars = len(full_text)
    logger.info(f"🔍 Iniciando extração — texto com {total_chars} caracteres")
    status_msg = await safe_send_message(update, 
        f"🔍 Extraindo itens do texto acumulado ({total_chars} caracteres)... Aguarde."
    )
    
    # Executa extração em thread separada para não travar o bot
    items = await asyncio.to_thread(extractor.extract_all, full_text)
    
    if not items:
        logger.info("❌ Nenhum item encontrado após extração")
        await safe_edit_message(status_msg, "❌ Nenhuma Seed/Key encontrada.")
        return

    total_items = len(items)
    logger.info(f"✅ Extração concluída — {total_items} itens únicos encontrados. Iniciando varredura de saldos...")
    await safe_edit_message(status_msg,
        f"✅ Extração concluída!\n"
        f"📦 {total_items} itens únicos encontrados.\n"
        f"💰 Iniciando varredura de saldos..."
    )
    found_count = 0

    for i, (item_type, val) in enumerate(items):
        try:
            res = await check_balance_master(item_type, val)
            if res:
                found_count += 1
                v, balances = res
                balance_summary = " | ".join(f"{coin}: {bal}" for coin, _addr, bal in balances)
                logger.info(
                    f"🎯 Saldo encontrado! [{i+1}/{total_items}] Tipo: {item_type} "
                    f"| Redes: {len(balances)} | {balance_summary}"
                )
                msg = format_found_message(item_type, v, balances)
                await safe_send_message(update, msg)
        except Exception as e:
            logger.error(f"Erro ao verificar item {i+1}/{total_items} ({item_type}): {e}")

        # Adiciona um delay maior para evitar flood (0.2s = 5 req/s max)
        await asyncio.sleep(0.2)

        if (i + 1) % 50 == 0: # Aumentado para 50 para reduzir drasticamente as edições
            logger.info(f"📊 Progresso: {i+1}/{total_items} | 🎯 Achados: {found_count}")
            await safe_edit_message(status_msg,
                f"🔍 Progresso: {i+1}/{total_items} | 🎯 Achados: {found_count}"
            )

    logger.info(f"✅ Varredura concluída — {total_items} itens verificados | {found_count} saldos encontrados")
    await safe_send_message(update,
        f"✅ Concluído!\n"
        f"📦 Itens verificados: {total_items}\n"
        f"🎯 Saldos encontrados: {found_count}"
    )
    user_pools[user_id] = []

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update): return
    user_id = update.effective_user.id
    text = ""

    if update.message.document:
        status = await safe_send_message(update, "⏳ Lendo arquivo... Isso pode levar alguns segundos.")
        try:
            file = await context.bot.get_file(update.message.document.file_id)
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                await file.download_to_drive(tmp.name)
                with open(tmp.name, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
            os.unlink(tmp.name)
            await safe_edit_message(status, f"✅ Arquivo de {len(text)} caracteres lido com sucesso. Use /check para processar.")
        except Exception as e:
            await safe_edit_message(status, f"❌ Erro ao ler arquivo: {e}")
            return
    elif update.message.text:
        text = update.message.text
        await safe_send_message(update, "📥 Texto adicionado. Use /check")

    if text.strip():
        if user_id not in user_pools: user_pools[user_id] = []
        user_pools[user_id].append(text)

async def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("clear", clear_pool))
    application.add_handler(CommandHandler("check", check_pool))
    application.add_handler(MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, handle_input))

    await application.initialize()
    await application.bot.delete_webhook(drop_pending_updates=True)
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    try: asyncio.run(main())
    except: pass
