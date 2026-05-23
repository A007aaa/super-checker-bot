import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_seed_balance

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8785377732:AAGEOY6H0Bo_mgvbymAJ-vWdmH08GMIQGnM')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🔐 **Bot de Verificação de Seed Phrase**\n\n"
        "Envie uma seed phrase (12 ou 24 palavras) e vou:\n"
        "✅ Gerar todos os endereços possíveis\n"
        "✅ Verificar saldo em:\n"
        "  • Bitcoin (Legacy, SegWit, Native)\n"
        "  • Ethereum\n"
        "  • BSC (BNB)\n"
        "  • Polygon (MATIC)\n"
        "  • Tron (TRX)\n\n"
        "⏳ Isso pode levar alguns minutos...",
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    seed_phrase = update.message.text.strip()
    
    if not seed_phrase:
        await update.message.reply_text("❌ Envie uma seed phrase válida.")
        return
    
    # Validar se parece uma seed phrase
    words = seed_phrase.split()
    if len(words) not in [12, 24]:
        await update.message.reply_text("❌ Seed phrase deve ter 12 ou 24 palavras.")
        return
    
    await update.message.reply_text("⏳ Analisando seed phrase... Isso pode levar alguns minutos.")
    
    result = await check_seed_balance(seed_phrase)
    
    if result:
        seed, balances = result
        msg = "✅ **SALDOS ENCONTRADOS!**\n\n"
        
        # Agrupar por moeda
        by_coin = {}
        for coin, addr, bal in balances:
            if coin not in by_coin:
                by_coin[coin] = []
            by_coin[coin].append((addr, bal))
        
        for coin in sorted(by_coin.keys()):
            msg += f"💰 **{coin}**\n"
            for addr, bal in by_coin[coin]:
                msg += f"  • `{addr[:20]}...` → {bal:.8f}\n"
            msg += "\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text("ℹ️ Nenhum saldo encontrado nesta seed phrase.")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
