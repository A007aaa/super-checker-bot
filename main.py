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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
extractor = SeedExtractor()

user_word_pools = {}
MAX_PARALLEL_SEEDS = 25 # Modo Hyper Turbo: Processa 25 seeds simultaneamente

def get_results_file_path(user_id):
    return f"achados_com_saldo_{user_id}.txt"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🚀 **MODO HYPER TURBO 2.0 ATIVADO!** ⚡🔥\n\nVarredura instantânea com prioridade em saldos confirmados. Envie suas palavras ou arquivos!")

async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_word_pools[user_id] = []
    await update.message.reply_text("🗑️ Memória limpa.")

async def save_result(user_id, seed, found_list):
    with open(get_results_file_path(user_id), "a") as f:
        f.write(f"SEED: {seed}\n")
        for c, a, b in found_list: f.write(f" - {c}: {b} (Addr: {a})\n")
        f.write("-" * 30 + "\n")

async def process_seed_silent(user_id, seed, update):
    try:
        res = await check_balance_all(seed)
        if res:
            seed, found = res
            await save_result(user_id, seed, found)
            msg = f"🎯 **SALDO ENCONTRADO!**\n`{seed}`\n"
            for c, a, b in found: msg += f"• {c}: {b}\n"
            await update.message.reply_text(msg, parse_mode='Markdown')
            return True
    except Exception as e:
        logger.error(f"Erro ao processar seed {seed}: {e}")
    return False

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
    # Processamento mais agressivo
    for i in range(0, total, MAX_PARALLEL_SEEDS):
        batch = seeds[i:i + MAX_PARALLEL_SEEDS]
        tasks = [process_seed_silent(user_id, seed, update) for seed in batch]
        results = await asyncio.gather(*tasks)
        found_count += sum(1 for r in results if r)
        
        # Atualização frequente de status
        progress = min(i + MAX_PARALLEL_SEEDS, total)
        # Atualização de status mais frequente, mas com um pequeno delay para não sobrecarregar o Telegram
        if (i // MAX_PARALLEL_SEEDS) % 5 == 0 or (i + MAX_PARALLEL_SEEDS) >= total:
            try:
                await status_msg.edit_text(f"🚀 Progresso: {progress}/{total} | 🎯 Achados: {found_count}")
            except Exception as e:
                logger.warning(f"Erro ao enviar mensagem de progresso: {e}")
        await asyncio.sleep(0.1) # Pequeno delay para evitar flood de edições de mensagem

    if found_count > 0:
        await update.message.reply_document(document=open(get_results_file_path(user_id), 'rb'), caption=f"✅ Varredura Concluída! {found_count} saldos localizados.")
    else:
        await update.message.reply_text(f"✅ Varredura Concluída. Total: {total} | Achados: 0")

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
    await update.message.reply_text(f"📥 {len(new_words)} palavras prontas. Use /check para iniciar.")

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN não está definido. Por favor, defina a variável de ambiente.")
        exit(1)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_pool))
    app.add_handler(CommandHandler("solve", check_pool)) # Alias para conveniência
    app.add_handler(CommandHandler("clear", clear_pool))
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, handle_input))
    
    print("Bot iniciado. Aguardando mensagens...")
    # Força bruta: drop_pending_updates=True limpa mensagens antigas e derruba instâncias em conflito
    app.run_polling(drop_pending_updates=True, close_loop=True)

if __name__ == "__main__":
    main()
