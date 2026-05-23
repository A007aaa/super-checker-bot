import os
import logging
import tempfile
import asyncio
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_balance_all
from seed_extractor import SeedExtractor

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8785377732:AAGEOY6H0Bo_mgvbymAJ-vWdmH08GMIQGnM')
extractor = SeedExtractor()

user_word_pools = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🚀 **Super Checker Estável Ativado!**\n\n"
        "1. Envie seus arquivos .txt ou textos.\n"
        "2. Digite /check para processar tudo.\n"
        "3. Use /clear para limpar a memória."
    )

async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_word_pools[user_id] = []
    await update.message.reply_text("🗑️ Memória limpa.")

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    words = user_word_pools.get(user_id, [])
    if not words:
        await update.message.reply_text("❌ Nenhuma palavra acumulada.")
        return

    full_text = " ".join(words)
    seeds = extractor.extract_all_seeds(full_text)
    total = len(seeds)
    
    status_msg = await update.message.reply_text(f"⚡ Verificando {total} combinações...")

    found_count = 0
    for i, seed in enumerate(seeds):
        try:
            res = await check_balance_all(seed)
            if res:
                found_count += 1
                seed, found = res
                msg = f"🎯 **ACHADO!**\nSeed: `{seed}`\n"
                for c, a, b in found: msg += f"• {c}: {b}\n"
                await update.message.reply_text(msg, parse_mode='Markdown')
            
            if (i + 1) % 50 == 0:
                await status_msg.edit_text(f"⏳ Progresso: {i+1}/{total} | Encontradas: {found_count}")
                await asyncio.sleep(1) # Evita 429 do Telegram
        except Exception as e:
            logger.error(f"Erro: {e}")

    await update.message.reply_text(f"✅ Concluído! Total: {total} | Encontradas: {found_count}")

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in user_word_pools: user_word_pools[user_id] = []

    text = ""
    if update.message.document:
        file = await context.bot.get_file(update.message.document.file_id)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            with open(tmp.name, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        os.unlink(tmp.name)
    else:
        text = update.message.text

    new_words = re.findall(r'\b[a-z]+\b', text.lower())
    user_word_pools[user_id].extend(new_words)
    
    # Resposta silenciosa para evitar 429 se o usuário enviar muitos arquivos
    try:
        await update.message.reply_text(f"📥 +{len(new_words)} palavras (Total: {len(user_word_pools[user_id])})")
    except: pass

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_pool))
    app.add_handler(CommandHandler("clear", clear_pool))
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, handle_input))
    app.run_polling()

if __name__ == "__main__":
    main()
