import os
import logging
import tempfile
import asyncio
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_balance_all
from seed_extractor import SeedExtractor

# Configurações de Log
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Variáveis de Ambiente
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("RAILWAY_STATIC_URL") or os.getenv("PUBLIC_DOMAIN") or os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.getenv("PORT", 8080))

extractor = SeedExtractor()
user_word_pools = {}
MAX_PARALLEL_SEEDS = 40

def get_results_file_path(user_id):
    return f"achados_com_saldo_{user_id}.txt"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🚀 **MODO SERVERLESS ATIVADO!** ⚡🔥\n\nO bot agora opera em modo Webhook para máxima economia e performance.")

async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_word_pools[user_id] = []
    await update.message.reply_text("🗑️ Memória limpa.")

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    words = user_word_pools.get(user_id, [])
    if not words:
        await update.message.reply_text("❌ Sem palavras. Envie texto ou arquivo primeiro.")
        return

    full_text = " ".join(words)
    seeds = extractor.extract_all_seeds(full_text)
    total = len(seeds)
    status_msg = await update.message.reply_text(f"⚡ Verificando {total} combinações...")

    found_count = 0
    for i in range(0, total, MAX_PARALLEL_SEEDS):
        batch = seeds[i:i + MAX_PARALLEL_SEEDS]
        results = await asyncio.gather(*[process_seed_silent(user_id, seed, update) for seed in batch], return_exceptions=True)
        found_count += sum(1 for r in results if isinstance(r, bool) and r)
        
        progress = min(i + MAX_PARALLEL_SEEDS, total)
        if (i // MAX_PARALLEL_SEEDS) % 5 == 0 or (i + MAX_PARALLEL_SEEDS) >= total:
            try: await status_msg.edit_text(f"🚀 Progresso: {progress}/{total} | 🎯 Achados: {found_count}")
            except: pass
        await asyncio.sleep(0.1)

    if found_count > 0:
        await update.message.reply_document(document=open(get_results_file_path(user_id), 'rb'), caption=f"✅ Varredura Concluída! {found_count} saldos.")
    else:
        await update.message.reply_text(f"✅ Varredura Concluída. Total: {total} | Achados: 0")

async def process_seed_silent(user_id, seed, update):
    try:
        res = await check_balance_all(seed)
        if res:
            seed, found = res
            with open(get_results_file_path(user_id), "a") as f:
                f.write(f"SEED: {seed}\n")
                for c, a, b in found: f.write(f" - {c}: {b} (Addr: {a})\n")
                f.write("-" * 30 + "\n")
            msg = f"🎯 **SALDO ENCONTRADO!**\n`{seed}`\n"
            for c, a, b in found: msg += f"• {c}: {b}\n"
            await update.message.reply_text(msg, parse_mode='Markdown')
            return True
    except: pass
    return False

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in user_word_pools: user_word_pools[user_id] = []
    text = ""
    if update.message.document:
        file = await context.bot.get_file(update.message.document.file_id)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            with open(tmp.name, 'r', encoding='utf-8', errors='ignore') as f: text = f.read()
        os.unlink(tmp.name)
    else: text = update.message.text
    new_words = re.findall(r'\b[a-z]+\b', text.lower())
    user_word_pools[user_id].extend(new_words)
    await update.message.reply_text(f"📥 {len(new_words)} palavras prontas. Use /check.")

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN ausente.")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_pool))
    app.add_handler(CommandHandler("solve", check_pool))
    app.add_handler(CommandHandler("clear", clear_pool))
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, handle_input))

    # Configuração de URL
    url = WEBHOOK_URL or "zucchini-playfulness-production.up.railway.app"
    url = url.replace("https://", "").replace("http://", "")
    
    logger.info(f"Iniciando em modo WEBHOOK na porta {PORT} em https://{url}")
    
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=f"/{TELEGRAM_BOT_TOKEN}",
        webhook_url=f"https://{url}/{TELEGRAM_BOT_TOKEN}",
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()
