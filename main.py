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
RESULTS_FILE = "achados_com_saldo.txt"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🚀 **Super Checker com Backup Ativado!**\n\n"
        "Agora todos os saldos encontrados serão salvos em um arquivo e enviados para você no final."
    )

async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_word_pools[user_id] = []
    await update.message.reply_text("🗑️ Memória limpa.")

async def save_result(seed, found_list):
    """Salva o resultado em um arquivo local para backup."""
    with open(RESULTS_FILE, "a") as f:
        f.write(f"SEED: {seed}\n")
        for c, a, b in found_list:
            f.write(f" - {c}: {b} (Addr: {a})\n")
        f.write("-" * 30 + "\n")

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    words = user_word_pools.get(user_id, [])
    if not words:
        await update.message.reply_text("❌ Nenhuma palavra acumulada.")
        return

    full_text = " ".join(words)
    seeds = extractor.extract_all_seeds(full_text)
    total = len(seeds)
    
    status_msg = await update.message.reply_text(f"⚡ Verificando {total} seeds. Resultados serão salvos em arquivo.")

    found_count = 0
    for i, seed in enumerate(seeds):
        try:
            res = await check_balance_all(seed)
            if res:
                found_count += 1
                seed, found = res
                # 1. Salva no arquivo de backup
                await save_result(seed, found)
                
                # 2. Tenta enviar mensagem no Telegram
                msg = f"🎯 **SALDO ENCONTRADO!**\nSeed: `{seed}`\n"
                for c, a, b in found: msg += f"• {c}: {b}\n"
                try:
                    await update.message.reply_text(msg, parse_mode='Markdown')
                except:
                    logger.error(f"Erro ao enviar mensagem de saldo para a seed: {seed}")
            
            if (i + 1) % 10 == 0 or (i + 1) == total:
                try:
                    await status_msg.edit_text(f"⏳ **Progresso:** {i+1}/{total}\n🎯 **Encontradas:** {found_count}")
                except: pass
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Erro: {e}")

    # Envia o arquivo de resultados no final se houver achados
    if found_count > 0 and os.path.exists(RESULTS_FILE):
        await update.message.reply_document(document=open(RESULTS_FILE, 'rb'), caption=f"✅ Verificação concluída! Aqui estão as {found_count} seeds com saldo.")
        # Opcional: deletar o arquivo após enviar para não acumular para o próximo usuário
        # os.remove(RESULTS_FILE)
    else:
        await update.message.reply_text(f"✅ Fim da verificação. Nenhuma seed com saldo encontrada entre as {total} testadas.")

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
    await update.message.reply_text(f"📥 +{len(new_words)} (Total: {len(user_word_pools[user_id])})")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_pool))
    app.add_handler(CommandHandler("clear", clear_pool))
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, handle_input))
    app.run_polling()

if __name__ == "__main__":
    main()
