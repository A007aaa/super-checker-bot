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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Bot Online no Render!")

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    words = user_word_pools.get(user_id, [])
    if not words:
        await update.message.reply_text("❌ Sem palavras.")
        return
    seeds = extractor.extract_all_seeds(" ".join(words))
    await update.message.reply_text(f"⚡ Verificando {len(seeds)} seeds...")
    for seed in seeds:
        res = await check_balance_all(seed)
        if res:
            s, found = res
            msg = f"🎯 **ACHADO!**\n`{s}`\n"
            for c, a, b in found: msg += f"• {c}: {b}\n"
            await update.message.reply_text(msg, parse_mode='Markdown')
    await update.message.reply_text("✅ Fim.")

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_word_pools: user_word_pools[user_id] = []
    text = update.message.text or ""
    new_words = re.findall(r'\b[a-z]+\b', text.lower())
    user_word_pools[user_id].extend(new_words)
    await update.message.reply_text(f"📥 {len(new_words)} palavras prontas.")

# --- Web Server ---
async def handle_root(request):
    return web.Response(text="Bot is running")

async def handle_webhook(request):
    app = request.app['bot_app']
    data = await request.json()
    update = Update.de_json(data, app.bot)
    await app.process_update(update)
    return web.Response(status=200)

async def main():
    if not TOKEN:
        logger.error("TOKEN MISSING")
        return

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_pool))
    app.add_handler(MessageHandler(filters.TEXT, handle_input))

    await app.initialize()
    await app.start()

    if DOMAIN:
        url = DOMAIN.replace("https://", "").replace("http://", "")
        await app.bot.set_webhook(f"https://{url}/{TOKEN}")
        logger.info(f"Webhook set: https://{url}/{TOKEN}")

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
