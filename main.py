import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_wallet_balance

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8785377732:AAGEOY6H0Bo_mgvbymAJ-vWdmH08GMIQGnM')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "💰 **Bot de Verificação de Saldo**\n\n"
        "Envie endereços de wallet para verificar saldo:\n"
        "• Bitcoin (BTC)\n"
        "• Ethereum (ETH)\n"
        "• BSC (BNB)\n"
        "• Polygon (MATIC)\n"
        "• Tron (TRX)\n\n"
        "Você pode enviar um endereço por linha ou separados por vírgula.",
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    
    if not text:
        await update.message.reply_text("❌ Envie pelo menos um endereço de wallet.")
        return
    
    addresses = [addr.strip() for addr in text.replace(',', '\n').split('\n') if addr.strip()]
    
    if not addresses:
        await update.message.reply_text("❌ Nenhum endereço válido encontrado.")
        return
    
    await update.message.reply_text(f"⏳ Verificando {len(addresses)} endereço(s)...")
    
    results = []
    for addr in addresses:
        result = await check_wallet_balance(addr)
        if result:
            results.append(result)
    
    if results:
        msg = "✅ **RESULTADOS:**\n\n"
        for addr, balances in results:
            msg += f"📍 `{addr}`\n"
            for coin, balance in balances:
                msg += f"  • {coin}: {balance}\n"
            msg += "\n"
        await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text("ℹ️ Nenhum saldo encontrado nos endereços verificados.")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
