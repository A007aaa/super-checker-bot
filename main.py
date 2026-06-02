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
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurações
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))
# Se não houver domínio configurado, assumimos que é LOCAL (PC)
DOMAIN = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_DOMAIN") or os.getenv("RAILWAY_STATIC_URL")

extractor = SeedExtractor()
user_word_pools = {}
MAX_PARALLEL_SEEDS = 80

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 **BOT INICIADO COM SUCESSO!**\n\nEnvie seus arquivos .txt ou palavras soltas e use /check para verificar saldos.")

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
        
    new_words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    user_word_pools[user_id].extend(new_words)
    await update.message.reply_text(f"📥 {len(new_words)} palavras prontas. Use /check.")

# --- Web Server (Health Check) ---
async def handle_root(request): return web.Response(text="OK")
async def handle_webhook(request):
    app = request.app['bot_app']
    update = Update.de_json(await request.json(), app.bot)
    await app.process_update(update)
    return web.Response(status=200)

async def run_web_server(app):
    web_app = web.Application()
    web_app['bot_app'] = app
    web_app.router.add_get('/', handle_root)
    web_app.router.add_post(f"/{TOKEN}", handle_webhook)
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

async def main():
    if not TOKEN:
        print("❌ ERRO: Defina a variável de ambiente TELEGRAM_BOT_TOKEN")
        return

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_pool))
    app.add_handler(CommandHandler("clear", clear_pool))
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, handle_input))

    if DOMAIN:
        # MODO NUVEM (WEBHOOK)
        logger.info("Iniciando em MODO WEBHOOK (Nuvem)")
        await app.initialize()
        await app.start()
        url = DOMAIN.replace("https://", "").replace("http://", "")
        await app.bot.set_webhook(f"https://{url}/{TOKEN}", drop_pending_updates=True)
        await run_web_server(app)
        while True: await asyncio.sleep(3600)
    else:
        # MODO LOCAL (POLLING)
        logger.info("Iniciando em MODO POLLING (Local/PC)")
        await app.initialize()
        await app.bot.delete_webhook(drop_pending_updates=True)
        await app.start()
        await app.updater.start_polling()
        while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
