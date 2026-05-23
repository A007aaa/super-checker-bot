import os
import logging
import tempfile
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_balance_all
from seed_extractor import SeedExtractor

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8785377732:AAGEOY6H0Bo_mgvbymAJ-vWdmH08GMIQGnM')
extractor = SeedExtractor()

# Limite de seeds processadas simultaneamente para não travar o servidor
MAX_PARALLEL_SEEDS = 10

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🚀 **Super Checker Ativado!**\n\nEnvie arquivos .txt com milhares de seeds. Eu vou processar tudo em paralelo e te avisar se encontrar saldo em qualquer rede!")

async def process_seed_and_notify(seed, update):
    """Processa uma única seed e notifica se encontrar saldo."""
    try:
        res = await check_balance_all(seed)
        if res:
            seed, found = res
            msg = f"🎯 **SALDO ENCONTRADO!**\n\n🔑 **Seed:** `{seed}`\n"
            for c, a, b in found:
                msg += f"• {c}: {b} (Addr: `{a}`)\n"
            await update.message.reply_text(msg, parse_mode='Markdown')
            return True
    except Exception as e:
        logger.error(f"Erro ao processar seed: {e}")
    return False

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    if not doc.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Por favor, envie apenas arquivos .txt")
        return

    status_msg = await update.message.reply_text("⏳ Baixando arquivo...")
    file = await context.bot.get_file(doc.file_id)
    
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        with open(tmp.name, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    os.unlink(tmp.name)

    seeds = extractor.extract_all_seeds(content)
    total = len(seeds)
    
    if total == 0:
        await status_msg.edit_text("❌ Nenhuma seed válida encontrada no arquivo.")
        return

    await status_msg.edit_text(f"⚡ **Iniciando processamento paralelo...**\nTotal: {total} seeds encontradas.\n\nIsso pode levar algum tempo dependendo do tamanho da lista.")

    # Processamento em lotes (Parallel Processing)
    found_count = 0
    for i in range(0, total, MAX_PARALLEL_SEEDS):
        batch = seeds[i:i + MAX_PARALLEL_SEEDS]
        tasks = [process_seed_and_notify(seed, update) for seed in batch]
        results = await asyncio.gather(*tasks)
        found_count += sum(1 for r in results if r)
        
        # Atualiza o status a cada lote
        if (i + MAX_PARALLEL_SEEDS) % 50 == 0 or (i + MAX_PARALLEL_SEEDS) >= total:
            progress = min(i + MAX_PARALLEL_SEEDS, total)
            await status_msg.edit_text(f"⏳ **Progresso:** {progress}/{total} seeds verificadas.\n🎯 **Encontradas:** {found_count}")

    await update.message.reply_text(f"✅ **Processamento Concluído!**\nTotal verificado: {total}\nSaldos encontrados: {found_count}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    seeds = extractor.extract_all_seeds(update.message.text)
    if not seeds:
        await update.message.reply_text("❌ Nenhuma seed válida encontrada.")
        return
    
    await update.message.reply_text(f"⏳ Verificando {len(seeds)} seeds...")
    for seed in seeds:
        await process_seed_and_notify(seed, update)
    await update.message.reply_text("✅ Verificação concluída.")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()
