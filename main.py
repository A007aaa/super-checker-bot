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
    if not update or not update.effective_user: return False
    return update.effective_user.id == ALLOWED_USER_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update): return
    await update.message.reply_text("🚀 **BOT ATUALIZADO!**\nEnvie seus arquivos .txt e use /check.")

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
    status_msg = await update.message.reply_text("🔍 Extraindo itens do texto acumulado... Aguarde.")
    
    # Executa extração em thread separada para não travar o bot
    items = await asyncio.to_thread(extractor.extract_all, full_text)
    
    if not items:
        await status_msg.edit_text("❌ Nenhuma Seed/Key encontrada.")
        return

    await status_msg.edit_text(f"🔍 Encontrados {len(items)} itens. Iniciando varredura de saldos...")
    found_count = 0

    for i, (item_type, val) in enumerate(items):
        try:
            res = await check_balance_master(item_type, val)
            if res:
                found_count += 1
                v, balances = res
                msg = f"🎯 **SALDO!** ({item_type})\n`{v}`\n"
                for c, a, b in balances: msg += f"• {c}: {b}\n"
                await update.message.reply_text(msg)
        except: pass
        
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
        status = await update.message.reply_text("⏳ Lendo arquivo... Isso pode levar alguns segundos.")
        try:
            file = await context.bot.get_file(update.message.document.file_id)
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                await file.download_to_drive(tmp.name)
                with open(tmp.name, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
            os.unlink(tmp.name)
            await status.edit_text(f"✅ Arquivo de {len(text)} caracteres lido com sucesso. Use /check para processar.")
        except Exception as e:
            await status.edit_text(f"❌ Erro ao ler arquivo: {e}")
            return
    elif update.message.text:
        text = update.message.text
        await update.message.reply_text("📥 Texto adicionado. Use /check")

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
