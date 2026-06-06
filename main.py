import os
import logging
import asyncio
import re
import tempfile
import nest_asyncio
from aiohttp import web
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import process_all_seeds
from seed_extractor import SeedExtractor

# Configuração de Logs
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurações
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))
DOMAIN = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_DOMAIN") or os.getenv("RAILWAY_STATIC_URL")

extractor = SeedExtractor()
user_word_pools = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 **MODO TURBO 4.0 ATIVADO!**\n\nProcessamento por Lotes (Batching) e Multiprocessing real iniciado.")

async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_word_pools[user_id] = []
    await update.message.reply_text("🗑️ Memória limpa.")

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    words = user_word_pools.get(user_id, [])
    
    if not words:
        await update.message.reply_text("❌ Sem palavras. Envie um arquivo ou texto primeiro.")
        return
    
    full_text = " ".join(words)
    seeds = extractor.extract_all_seeds(full_text)
    total = len(seeds)
    
    if total == 0:
        await update.message.reply_text("⚠️ Nenhuma seed válida encontrada na lista.")
        return

    status_msg = await update.message.reply_text(f"⚡ Seeds: {total}\n🚀 Iniciando Varredura Ultra-Sônica...")
    
    # Processar todas as seeds usando o novo sistema de Batching
    # O process_all_seeds já gerencia o paralelismo e o batching interno
    results_map = await process_all_seeds(seeds)
    
    found_count = 0
    for seed, findings in results_map.items():
        msg = f"🎯 **ACHADO!**\n`{seed}`\n"
        for net, addr, bal in findings:
            msg += f"• {net}: {bal:.6f}\n"
        await update.message.reply_text(msg, parse_mode='Markdown')
        found_count += 1
        
    await update.message.reply_text(f"✅ **Fim da Varredura!**\n\nTotal Processado: {total}\nAchados com Saldo: {found_count}")

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        text = update.message.text or ""
        
    # Extrator otimizado para identificar palavras BIP39 rapidamente
    new_words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    user_word_pools[user_id].extend(new_words)
    await update.message.reply_text(f"📥 Recebidas {len(new_words)} palavras.\nTotal na memória: {len(user_word_pools[user_id])}\n\nUse /check para iniciar.")

# Web Server simplificado para Health Check
async def handle_root(request): return web.Response(text="OK")
async def run_web_server():
    web_app = web.Application()
    web_app.router.add_get('/', handle_root)
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

async def main():
    if not TOKEN:
        logger.error("Token não configurado!")
        return
        
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_pool))
    app.add_handler(CommandHandler("clear", clear_pool))
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, handle_input))

    if DOMAIN:
        await app.initialize()
        await app.start()
        await app.bot.set_webhook(f"https://{DOMAIN.replace('https://','').replace('http://','')}/{TOKEN}")
        await run_web_server()
        while True: await asyncio.sleep(3600)
    else:
        await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
