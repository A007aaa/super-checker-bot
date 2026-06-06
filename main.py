import os
import logging
import asyncio
import re
import tempfile
import nest_asyncio
from aiohttp import web
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_balance_all
from seed_extractor import SeedExtractor
from concurrent.futures import ThreadPoolExecutor

# Configuração de Logs
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurações de Performance
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))
DOMAIN = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_DOMAIN") or os.getenv("RAILWAY_STATIC_URL")

extractor = SeedExtractor()
user_word_pools = {}
# Aumentado para velocidade extrema no PC
MAX_PARALLEL_SEEDS = 150 
executor = ThreadPoolExecutor(max_workers=20)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 **MODO TURBO ATIVADO!**\n\nEnvie suas listas e use /check para varredura ultra-rápida.")

async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_word_pools[user_id] = []
    await update.message.reply_text("🗑️ Memória limpa.")

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    words = user_word_pools.get(user_id, [])
    
    if not words:
        await update.message.reply_text("❌ Sem palavras na memória.")
        return
    
    full_text = " ".join(words)
    # Extração agora é instantânea
    seeds = extractor.extract_all_seeds(full_text)
    total = len(seeds)
    
    if total == 0:
        await update.message.reply_text("⚠️ Nenhuma seed válida encontrada.")
        return

    status_msg = await update.message.reply_text(f"⚡ Seeds: {total}\n🚀 Iniciando Varredura Ultra-Rápida...")
    
    found_count = 0
    # Processamento em lotes gigantes para velocidade máxima
    for i in range(0, total, MAX_PARALLEL_SEEDS):
        batch = seeds[i:i + MAX_PARALLEL_SEEDS]
        # Dispara tudo em paralelo real
        tasks = [check_balance_all(seed) for seed in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res in results:
            if res and not isinstance(res, Exception):
                s, found = res
                msg = f"🎯 **ACHADO!**\n`{s}`\n"
                for net, addr, bal in found:
                    msg += f"• {net}: {bal:.6f}\n"
                await update.message.reply_text(msg, parse_mode='Markdown')
                found_count += 1
        
        # Atualização de progresso mais rápida
        if (i + MAX_PARALLEL_SEEDS) < total:
            try:
                await status_msg.edit_text(f"🚀 {min(i + MAX_PARALLEL_SEEDS, total)}/{total} | 🎯 {found_count}")
            except: pass
        
    await update.message.reply_text(f"✅ Concluído! Total: {total} | Achados: {found_count}")

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
        
    new_words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    user_word_pools[user_id].extend(new_words)
    await update.message.reply_text(f"📥 {len(new_words)} palavras (Total: {len(user_word_pools[user_id])}). Use /check.")

# Web Server simplificado para nuvem
async def handle_root(request): return web.Response(text="OK")
async def run_web_server(app):
    web_app = web.Application()
    web_app.router.add_get('/', handle_root)
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

async def main():
    if not TOKEN: return
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_pool))
    app.add_handler(CommandHandler("clear", clear_pool))
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, handle_input))

    if DOMAIN:
        await app.initialize()
        await app.start()
        await app.bot.set_webhook(f"https://{DOMAIN.replace('https://','').replace('http://','')}/{TOKEN}")
        await run_web_server(app)
        while True: await asyncio.sleep(3600)
    else:
        await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
