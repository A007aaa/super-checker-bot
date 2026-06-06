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
DOMAIN = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_DOMAIN") or os.getenv("RAILWAY_STATIC_URL")

extractor = SeedExtractor()
user_word_pools = {}
MAX_PARALLEL_SEEDS = 40 # Reduzi um pouco para estabilidade no PC e RPC

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 **SUPER CHECKER ATIVO!**\n\n1. Envie seu arquivo .txt ou cole as palavras.\n2. Use /check para iniciar a busca.\n3. Use /clear para limpar a memória.")

async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_word_pools[user_id] = []
    await update.message.reply_text("🗑️ Memória limpa com sucesso.")

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    words = user_word_pools.get(user_id, [])
    
    if not words:
        await update.message.reply_text("❌ Nenhuma palavra encontrada na memória. Envie um arquivo ou texto primeiro.")
        return
    
    await update.message.reply_text(f"🔍 Analisando {len(words)} palavras...")
    
    full_text = " ".join(words)
    seeds = extractor.extract_all_seeds(full_text)
    total = len(seeds)
    
    if total == 0:
        await update.message.reply_text("⚠️ Nenhuma frase-semente (12/24 palavras) válida encontrada. Verifique se as palavras estão corretas.")
        return

    status_msg = await update.message.reply_text(f"⚡ Encontradas {total} seeds válidas matematicamente.\nIniciando verificação de saldo...")
    
    found_count = 0
    for i in range(0, total, MAX_PARALLEL_SEEDS):
        batch = seeds[i:i + MAX_PARALLEL_SEEDS]
        tasks = [check_balance_all(seed) for seed in batch]
        results = await asyncio.gather(*tasks)
        
        for res in results:
            if res:
                s, found = res
                msg = f"🎯 **SALDO ENCONTRADO!**\n\n`{s}`\n\n"
                for net, addr, bal in found:
                    msg += f"💰 {net}: {bal:.6f}\n"
                await update.message.reply_text(msg, parse_mode='Markdown')
                found_count += 1
        
        if (i + MAX_PARALLEL_SEEDS) < total:
            try:
                await status_msg.edit_text(f"🚀 Progresso: {min(i + MAX_PARALLEL_SEEDS, total)}/{total} | 🎯 Sucessos: {found_count}")
            except: pass
        
    await update.message.reply_text(f"✅ Fim da varredura!\n\nTotal de seeds: {total}\nCom saldo: {found_count}")

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_word_pools: user_word_pools[user_id] = []
    
    text = ""
    if update.message.document:
        await update.message.reply_text("📥 Baixando arquivo...")
        file = await context.bot.get_file(update.message.document.file_id)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            with open(tmp.name, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        os.unlink(tmp.name)
    else:
        text = update.message.text or ""
        
    # Extrair apenas palavras que podem ser parte de uma seed (letras a-z, min 3 letras)
    new_words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    user_word_pools[user_id].extend(new_words)
    await update.message.reply_text(f"✅ {len(new_words)} palavras adicionadas à memória.\nTotal agora: {len(user_word_pools[user_id])}\n\nUse /check para começar.")

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
        logger.error("TELEGRAM_BOT_TOKEN não definido!")
        return

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_pool))
    app.add_handler(CommandHandler("clear", clear_pool))
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, handle_input))

    if DOMAIN:
        logger.info("MODO WEBHOOK ATIVO")
        await app.initialize()
        await app.start()
        url = DOMAIN.replace("https://", "").replace("http://", "")
        await app.bot.set_webhook(f"https://{url}/{TOKEN}", drop_pending_updates=True)
        await run_web_server(app)
        while True: await asyncio.sleep(3600)
    else:
        logger.info("MODO POLLING ATIVO")
        await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
