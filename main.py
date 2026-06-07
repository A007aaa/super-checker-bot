import os
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

async def is_authorized(update: Update) -> bool:
    if not update or not update.effective_user:
        return False
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        logger.warning(f"Acesso negado: {user_id}")
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update): return
    await update.message.reply_text(
        "🚀 **BOT PRONTO NO RAILWAY!** 🚀\n\n"
        "Envie textos ou encaminhe arquivos .txt com suas seeds.\n"
        "Use /check para iniciar a varredura."
    )

async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update): return
    user_pools[update.effective_user.id] = []
    await update.message.reply_text("🗑️ Memória limpa.")

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update): return
    user_id = update.effective_user.id
    pool = user_pools.get(user_id, [])
    if not pool:
        await update.message.reply_text("❌ Nada para verificar.")
        return

    full_text = " ".join(pool)
    items = extractor.extract_all(full_text)
    if not items:
        await update.message.reply_text("❌ Nenhuma Seed/Key encontrada no conteúdo acumulado.")
        return

    status_msg = await update.message.reply_text(f"🔍 Analisando {len(items)} itens...")
    found_count = 0

    for i, (item_type, val) in enumerate(items):
        try:
            res = await check_balance_master(item_type, val)
            if res:
                found_count += 1
                seed_val, balances = res
                msg = f"🎯 **SALDO ENCONTRADO!** ({item_type})\n`{seed_val}`\n"
                for coin, addr, bal in balances:
                    msg += f"• {coin}: {bal} (`{addr}`)\n"
                await update.message.reply_text(msg)
        except Exception as e:
            logger.error(f"Erro: {e}")
        
        if (i + 1) % 10 == 0:
            try: await status_msg.edit_text(f"🔍 Progresso: {i+1}/{len(items)} | 🎯 Achados: {found_count}")
            except: pass

    await update.message.reply_text(f"✅ Concluído! Itens: {len(items)} | Achados: {found_count}")
    user_pools[user_id] = []

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update): return
    user_id = update.effective_user.id
    text = ""

    if update.message.document:
        try:
            file = await context.bot.get_file(update.message.document.file_id)
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                await file.download_to_drive(tmp.name)
                with open(tmp.name, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
            os.unlink(tmp.name)
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao ler arquivo: {e}")
            return
    elif update.message.text:
        text = update.message.text

    if text.strip():
        if user_id not in user_pools: user_pools[user_id] = []
        user_pools[user_id].append(text)
        items = extractor.extract_all(text)
        await update.message.reply_text(f"📥 Recebido. ({len(items)} itens detectados). Use /check")

async def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("clear", clear_pool))
    application.add_handler(CommandHandler("check", check_pool))
    application.add_handler(MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, handle_input))

    logger.info("Iniciando...")
    await application.initialize()
    await application.bot.delete_webhook(drop_pending_updates=True)
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    try: asyncio.run(main())
    except: pass
