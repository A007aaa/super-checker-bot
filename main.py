import os
import logging
import tempfile
import time
import asyncio
import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_balance_all, get_universal_addresses
from seed_extractor import SeedExtractor

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8785377732:AAGEOY6H0Bo_mgvbymAJ-vWdmH08GMIQGnM')
extractor = SeedExtractor()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🤖 **Bot de Diagnóstico Ativado**\n\nEnvie uma seed ou arquivo .txt. Eu vou te mostrar os endereços que estou gerando para você conferir com sua carteira.\n\nComandos:\n/start - Inicia o bot\n/processar - Processa uma seed ou arquivo")

async def processar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /processar para iniciar processamento"""
    await update.message.reply_text("📝 Envie uma seed ou arquivo .txt para processar.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    seeds = extractor.extract_all_seeds(text)
    if not seeds:
        await update.message.reply_text("❌ Nenhuma seed válida encontrada.")
        return

    for seed in seeds:
        await update.message.reply_text(f"🔍 **Analisando Seed:** `{seed}`")
        # Mostrar endereços gerados para conferência
        addrs = await get_universal_addresses(seed)
        debug_msg = "📍 **Endereços Gerados (Primeiros de cada rede):**\n"
        for coin, label, addr in addrs[:5]: # Mostra os 5 primeiros para não inundar o chat
            debug_msg += f"• {coin} ({label}): `{addr}`\n"
        await update.message.reply_text(debug_msg, parse_mode='Markdown')
        
        # Verificar saldo
        res = await check_balance_all(seed)
        if res:
            seed, found = res
            msg = "✅ **SALDO ENCONTRADO!**\n"
            for c, a, b in found: msg += f"• {c}: {b} (Addr: `{a}`)\n"
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("ℹ️ Nenhum saldo encontrado nesses endereços.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    file = await context.bot.get_file(doc.file_id)
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        with open(tmp.name, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    os.unlink(tmp.name)
    # Para arquivos, processamos sem o debug detalhado para não travar o bot
    seeds = extractor.extract_all_seeds(content)
    await update.message.reply_text(f"⏳ Processando {len(seeds)} seeds do arquivo...")
    for seed in seeds:
        res = await check_balance_all(seed)
        if res:
            seed, found = res
            msg = f"🎯 **ACHADO!**\nSeed: `{seed}`\n"
            for c, a, b in found: msg += f"• {c}: {b}\n"
            await update.message.reply_text(msg, parse_mode='Markdown')
    await update.message.reply_text("✅ Fim do processamento do arquivo.")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("processar", processar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.run_polling()

if __name__ == "__main__":
    main()
