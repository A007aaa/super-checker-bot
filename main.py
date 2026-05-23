import os
import logging
import asyncio
import tempfile
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_balance_all
from seed_extractor import SeedExtractor

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8785377732:AAGEOY6H0Bo_mgvbymAJ-vWdmH08GMIQGnM')
extractor = SeedExtractor()

# Armazenar arquivos temporariamente por usuário
user_files = {}

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
        "Você pode enviar:\n"
        "  • Texto direto\n"
        "  • VÁRIOS arquivos .txt de uma vez\n"
        "  • Depois envie /processar para analisar todos\n\n"
        "⏳ Isso pode levar vários minutos para listas grandes...",
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    
    if not text:
        await update.message.reply_text("❌ Envie um texto com seed phrases.")
        return
    
    await process_seeds(update, text)

async def handle_documents(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Acumula múltiplos arquivos .txt"""
    doc = update.message.document
    user_id = update.effective_user.id
    
    if not doc.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Envie arquivo(s) .txt")
        return
    
    try:
        # Inicializar lista de arquivos do usuário se não existir
        if user_id not in user_files:
            user_files[user_id] = []
        
        # Baixar arquivo
        file = await context.bot.get_file(doc.file_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as tmp:
            await file.download_to_drive(tmp.name)
            with open(tmp.name, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        os.unlink(tmp.name)
        
        # Armazenar conteúdo
        user_files[user_id].append(content)
        
        await update.message.reply_text(
            f"✅ Arquivo '{doc.file_name}' recebido!\n\n"
            f"📁 Total de arquivos: {len(user_files[user_id])}\n\n"
            "Envie mais arquivos ou digite /processar para analisar todos"
        )
    except Exception as e:
        logger.error(f"Erro ao processar arquivo: {e}")
        await update.message.reply_text(f"❌ Erro ao processar arquivo: {str(e)}")

async def process_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa todos os arquivos acumulados"""
    user_id = update.effective_user.id
    
    logger.info(f"Comando /processar recebido do usuário {user_id}")
    logger.info(f"Arquivos armazenados: {user_files}")
    
    if user_id not in user_files or not user_files[user_id]:
        await update.message.reply_text("❌ Nenhum arquivo foi enviado. Envie arquivos .txt primeiro.")
        return
    
    # Juntar todo o conteúdo
    combined_text = "\n".join(user_files[user_id])
    
    # Limpar arquivos do usuário
    del user_files[user_id]
    
    await process_seeds(update, combined_text)

async def process_seeds(update: Update, text: str) -> None:
    """Processa seeds do texto"""
    seeds = extractor.extract_all_seeds(text)
    
    if not seeds:
        await update.message.reply_text("❌ Nenhuma seed phrase válida encontrada.")
        return
    
    await update.message.reply_text(f"⏳ Encontradas {len(seeds)} seed(s). Analisando... Isso pode levar alguns minutos.")
    
    results = []
    for i, seed in enumerate(seeds, 1):
        logger.info(f"Verificando seed {i}/{len(seeds)}: {seed[:30]}...")
        result = await check_balance_all(seed)
        if result:
            results.append(result)
    
    if results:
        msg = f"✅ **SALDOS ENCONTRADOS EM {len(results)} SEED(S)!**\n\n"
        
        for seed_idx, (seed, balances) in enumerate(results, 1):
            msg += f"🔐 **Seed #{seed_idx}:** `{seed[:40]}...`\n"
            
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
    
    # Ordem importante: comandos ANTES de message handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("processar", process_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_documents))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    app.run_polling()

if __name__ == "__main__":
    main()
