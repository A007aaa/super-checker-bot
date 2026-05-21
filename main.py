import os
import tempfile
import time
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_balance_all
from seed_extractor import SeedExtractor

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8785377732:AAGEOY6H0Bo_mgvbymAJ-vWdmH08GMIQGnM')

user_buffers = {}
BATCH_WAIT_TIME = 10
MAX_FILE_SIZE = 50 * 1024 * 1024
extractor = SeedExtractor()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = """🤖 **Bot Multi-Blockchain USDT Checker**

Suporta 30+ blockchains:
• Bitcoin (3 formatos), Ethereum, Solana, BNB Chain
• Avalanche, Cardano, Polkadot, Cosmos, Near, Algorand
• Tezos, Aptos, Sui, Toncoin, Tron, XRP, Litecoin
• Monero, Arbitrum, Optimism, Base, Polygon, zkSync
• Starknet, Linea, Immutable, Ronin, Flow, WAX
• Zcash, Secret, Chainlink, Hedera, Quant

📝 **Como usar:**
1. Envie seeds (12, 15, 18, 21 ou 24 palavras)
2. Palavras separadas por espaço OU juntas (sem espaços)
3. Ou envie arquivo .txt com múltiplas seeds
4. Bot processa até 100k+ combinações
5. Retorna apenas endereços com saldo em USDT

⚠️ **Apenas para suas próprias carteiras!**"""
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def process_batch(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    if chat_id not in user_buffers:
        return
    buffer = user_buffers[chat_id]
    if buffer['timer']:
        buffer['timer'].cancel()

    async def run_task():
        await asyncio.sleep(BATCH_WAIT_TIME)
        all_text = "\n".join(buffer['contents'])
        del user_buffers[chat_id]
        
        seeds = extractor.extract_all_seeds(all_text)
        if not seeds:
            await context.bot.send_message(chat_id=chat_id, text="❌ Nenhuma seed válida encontrada.")
            return
        
        await context.bot.send_message(chat_id=chat_id, text=f"⏳ Processando {len(seeds)} seeds em múltiplas blockchains...\n\n⏱️ Isso pode levar alguns minutos...")
        
        semaphore = asyncio.Semaphore(10)
        
        async def check_with_semaphore(seed):
            async with semaphore:
                return await check_balance_all(seed)
        
        tasks = [check_with_semaphore(seed) for seed in seeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        positivos = [r for r in results if r is not None and not isinstance(r, Exception)]
        
        response = [
            "═══════════════════════════════",
            "📊 RELATÓRIO FINAL",
            "═══════════════════════════════",
            f"✓ Seeds testadas: {len(seeds)}",
            f"✓ Saldos encontrados: {len(positivos)}",
            "═══════════════════════════════"
        ]
        
        if positivos:
            for seed, found_list in positivos:
                msg = f"\n🎯 **CARTEIRA COM SALDO**\n"
                msg += f"Seed: `{seed}`\n"
                msg += "─────────────────────\n"
                for coin, addr, bal in found_list:
                    msg += f"• {coin}: {bal:.6f}\n"
                    msg += f"  Addr: `{addr}`\n"
                response.append(msg)
        else:
            response.append("\n❌ Nenhum saldo detectado em nenhuma blockchain.")
            
        final_msg = "\n".join(response)
        
        if len(final_msg) > 4000:
            for i in range(0, len(final_msg), 4000):
                await context.bot.send_message(chat_id=chat_id, text=final_msg[i:i+4000], parse_mode='Markdown')
        else:
            await context.bot.send_message(chat_id=chat_id, text=final_msg, parse_mode='Markdown')

    buffer['timer'] = asyncio.create_task(run_task())

async def add_to_buffer(chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    if chat_id not in user_buffers:
        user_buffers[chat_id] = {'contents': [], 'timer': None}
    user_buffers[chat_id]['contents'].append(text)
    await process_batch(chat_id, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text:
        await add_to_buffer(update.effective_chat.id, update.message.text, context)
        await update.message.reply_text("✅ Adicionado ao lote...")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    
    if document.file_size and document.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(f"❌ Arquivo muito grande! Máximo: 50 MB\nTamanho: {document.file_size / (1024*1024):.2f} MB")
        return
    
    file_id = document.file_id
    new_file = await context.bot.get_file(file_id)
    temp_path = os.path.join(tempfile.gettempdir(), f"tmp_{int(time.time())}")
    
    try:
        await update.message.reply_text(f"📥 Baixando '{document.file_name}'...")
        await new_file.download_to_drive(temp_path)
        
        file_size = os.path.getsize(temp_path)
        if file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ Arquivo muito grande! Máximo: 50 MB\nTamanho: {file_size / (1024*1024):.2f} MB")
            return
        
        with open(temp_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        await update.message.reply_text(f"✅ '{document.file_name}' adicionado ao lote...")
        await add_to_buffer(update.effective_chat.id, content, context)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao processar arquivo: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    print("🚀 Bot Multi-Blockchain rodando...")
    application.run_polling()

if __name__ == "__main__":
    main()
