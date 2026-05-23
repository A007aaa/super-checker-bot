import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_seed_balance
from seed_extractor import SeedExtractor

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8785377732:AAGEOY6H0Bo_mgvbymAJ-vWdmH08GMIQGnM')
extractor = SeedExtractor()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🔐 **Bot de Verificação de Seed Phrases**\n\n"
        "Envie uma lista com múltiplas seed phrases e vou:\n"
        "✅ Extrair todas as seeds (mesmo juntas)\n"
        "✅ Gerar todos os endereços possíveis\n"
        "✅ Verificar saldo em:\n"
        "  • Bitcoin (Legacy, SegWit, Native)\n"
        "  • Ethereum\n"
        "  • BSC (BNB)\n"
        "  • Polygon (MATIC)\n"
        "  • Tron (TRX)\n\n"
        "⏳ Isso pode levar vários minutos para listas grandes...",
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    
    if not text:
        await update.message.reply_text("❌ Envie um texto com seed phrases.")
        return
    
    # Extrair todas as seeds do texto
    seeds = extractor.extract_all_seeds(text)
    
    if not seeds:
        await update.message.reply_text("❌ Nenhuma seed phrase válida encontrada.")
        return
    
    await update.message.reply_text(f"⏳ Encontradas {len(seeds)} seed(s). Analisando... Isso pode levar alguns minutos.")
    
    # Verificar cada seed
    results = []
    for i, seed in enumerate(seeds, 1):
        logger.info(f"Verificando seed {i}/{len(seeds)}: {seed[:30]}...")
        result = await check_seed_balance(seed)
        if result:
            results.append(result)
    
    if results:
        msg = f"✅ **SALDOS ENCONTRADOS EM {len(results)} SEED(S)!**\n\n"
        
        for seed_idx, (seed, balances) in enumerate(results, 1):
            msg += f"🔐 **Seed #{seed_idx}:** `{seed[:40]}...`\n"
            
            # Agrupar por moeda
            by_coin = {}
            for coin, addr, bal in balances:
                if coin not in by_coin:
                    by_coin[coin] = []
                by_coin[coin].append((addr, bal))
            
            for coin in sorted(by_coin.keys()):
                msg += f"  💰 **{coin}**\n"
                for addr, bal in by_coin[coin]:
                    msg += f"    • `{addr[:20]}...` → {bal:.8f}\n"
            msg += "\n"
        
        # Dividir mensagem se ficar muito grande
        if len(msg) > 4000:
            chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode='Markdown')
        else:
            await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(f"ℹ️ Analisadas {len(seeds)} seed(s), mas nenhum saldo foi encontrado.")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
