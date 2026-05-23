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

# Dicionário para armazenar as palavras acumuladas por usuário
user_word_pools = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📥 **Modo Coletor Ativado!**\n\n"
        "1. Envie quantos arquivos .txt ou textos quiser.\n"
        "2. Eu vou juntar todas as palavras em um único grupo.\n"
        "3. Quando terminar, digite /check para eu procurar todas as combinações de seeds.\n"
        "4. Use /clear para limpar sua lista de palavras."
    )

async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_word_pools[user_id] = []
    await update.message.reply_text("🗑️ Sua lista de palavras foi limpa.")

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    words = user_word_pools.get(user_id, [])
    
    if not words:
        await update.message.reply_text("❌ Você ainda não enviou nenhuma palavra. Envie arquivos .txt primeiro!")
        return

    full_text = " ".join(words)
    seeds = extractor.extract_all_seeds(full_text)
    total = len(seeds)
    
    status_msg = await update.message.reply_text(f"⚡ Encontradas {total} combinações de seeds. Iniciando verificação universal...")

    found_count = 0
    for i, seed in enumerate(seeds):
        res = await check_balance_all(seed)
        if res:
            found_count += 1
            seed, found = res
            msg = f"🎯 **ACHADO!**\nSeed: `{seed}`\n"
            for c, a, b in found: msg += f"• {c}: {b}\n"
            await update.message.reply_text(msg, parse_mode='Markdown')
        
        if (i + 1) % 20 == 0:
            await status_msg.edit_text(f"⏳ Progresso: {i+1}/{total} | Encontradas: {found_count}")

    await update.message.reply_text(f"✅ Verificação concluída!\nTotal de seeds testadas: {total}\nSaldos encontrados: {found_count}")

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in user_word_pools:
        user_word_pools[user_id] = []

    text = ""
    if update.message.document:
        doc = update.message.document
        file = await context.bot.get_file(doc.file_id)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            with open(tmp.name, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        os.unlink(tmp.name)
    else:
        text = update.message.text

    # Extrair apenas palavras (letras) e adicionar ao pool
    new_words = re.findall(r'\b[a-z]+\b', text.lower())
    user_word_pools[user_id].extend(new_words)
    
    await update.message.reply_text(f"📥 Adicionadas {len(new_words)} palavras. Total acumulado: {len(user_word_pools[user_id])} palavras.\n\nEnvie mais ou digite /check para começar.")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_pool))
    app.add_handler(CommandHandler("clear", clear_pool))
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, handle_input))
    app.run_polling()

if __name__ == "__main__":
    main()
