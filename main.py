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
MAX_PARALLEL_SEEDS = 100 # Modo Hyper Turbo: 100 seeds por vez
RESULTS_FILE = "achados_com_saldo.txt"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🚀 **MODO HYPER TURBO ATIVADO!** ⚡🔥\n\nProcessando 100 seeds simultaneamente. Velocidade máxima de varredura.")

async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_word_pools[user_id] = []
    await update.message.reply_text("🗑️ Memória limpa.")

async def save_result(seed, found_list):
    with open(RESULTS_FILE, "a") as f:
        f.write(f"SEED: {seed}\n")
        for c, a, b in found_list: f.write(f" - {c}: {b} (Addr: {a})\n")
        f.write("-" * 30 + "\n")

async def process_seed_silent(seed, update):
    try:
        res = await check_balance_all(seed)
        if res:
            seed, found = res
            await save_result(seed, found)
            msg = f"🎯 **SALDO ENCONTRADO!**\nSeed: `{seed}`\n"
            for c, a, b in found: msg += f"• {c}: {b}\n"
            await update.message.reply_text(msg, parse_mode='Markdown')
            return True
    except: pass
    return False

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    words = user_word_pools.get(user_id, [])
    if not words:
        await update.message.reply_text("❌ Nenhuma palavra acumulada.")
        return

    full_text = " ".join(words)
    seeds = extractor.extract_all_seeds(full_text)
    total = len(seeds)
    
    status_msg = await update.message.reply_text(f"⚡ **HYPER TURBO:** Verificando {total} seeds...")

    found_count = 0
    for i in range(0, total, MAX_PARALLEL_SEEDS):
        batch = seeds[i:i + MAX_PARALLEL_SEEDS]
        tasks = [process_seed_silent(seed, update) for seed in batch]
        results = await asyncio.gather(*tasks)
        found_count += sum(1 for r in results if r)
        
        if (i + MAX_PARALLEL_SEEDS) % 500 == 0 or (i + MAX_PARALLEL_SEEDS) >= total:
            progress = min(i + MAX_PARALLEL_SEEDS, total)
            try:
                await status_msg.edit_text(f"🚀 **Hyper:** {progress}/{total} | 🎯 **Achados:** {found_count}")
            except: pass
            await asyncio.sleep(1)

    if found_count > 0 and os.path.exists(RESULTS_FILE):
        await update.message.reply_document(document=open(RESULTS_FILE, 'rb'), caption=f"✅ Fim do Hyper Turbo! {found_count} achados.")
    else:
        await update.message.reply_text(f"✅ Fim do Hyper Turbo! Total: {total} | Achados: 0")

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
    try:
        await update.message.reply_text(f"📥 +{len(new_words)} (Total: {len(user_word_pools[user_id])})")
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
