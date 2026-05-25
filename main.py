import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_balance_master
from seed_extractor import SeedExtractor

# Configuração de Logging
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configurações do Bot
# Token atualizado para evitar conflitos de instância
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8785377732:AAEq7f-65k_Obwy9xhmBgKEoGBO8qOhkQys")
if not TELEGRAM_BOT_TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN não configurado. O bot não pode iniciar.")
    exit(1)
# O bot agora aceita qualquer usuário que interagir com ele (Removida trava de ID)
ALLOWED_USER_ID = None 

extractor = SeedExtractor()
user_pools = {}

async def is_authorized(update: Update) -> bool:
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🚀 **SUPER CHECKER OTIMIZADO** 🚀\n\n"
        "Envie textos ou arquivos `.txt`.\n"
        "Comandos:\n"
        "🔍 /check - Inicia a varredura\n"
        "📊 /status - Ver fila\n"
        "🗑️ /clear - Limpar fila"
    )

async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    user_id = update.effective_user.id
    user_pools[user_id] = set()
    await update.message.reply_text("🗑️ Fila de verificação limpa.")

async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    user_id = update.effective_user.id
    count = len(user_pools.get(user_id, set()))
    await update.message.reply_text(f"📊 **Status da Fila:** {count} itens aguardando verificação.")

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    
    user_id = update.effective_user.id
    pool = user_pools.get(user_id, set())
    
    if not pool:
        await update.message.reply_text("❌ Nada para verificar na memória. Envie arquivos primeiro.")
        return

    items_list = list(pool)
    total = len(items_list)
    await update.message.reply_text(f"🔍 Iniciando varredura de **{total}** itens únicos...")
    
    status_msg = await update.message.reply_text("⏳ Processando: 0%")
    found_count = 0

    # MODO TURBO: Processamento paralelo de múltiplas seeds
    async def check_and_report(i, val):
        nonlocal found_count
        words_count = len(val.split())
        item_type = "SEED" if words_count in [12, 15, 18, 21, 24] else "KEY_SOL"
        if len(val) == 64 and " " not in val:
            item_type = "KEY_HEX"
        
        try:
            res = await check_balance_master(item_type, val)
            if res:
                found_count += 1
                seed_val, balances = res
                msg = f"🎯 **SALDO ENCONTRADO!** ({item_type})\n`{seed_val}`\n"
                for coin, addr, bal in balances:
                    msg += f"• **{coin}**: `{bal}`\n  └ Endereço: `{addr}`\n"
                await update.message.reply_text(msg)
        except Exception as e:
            logger.error(f"Erro ao verificar item {i}: {e}")

    # Processamento de Alta Performance: 5 seeds por vez
    batch_size = 5
    for i in range(0, total, batch_size):
        batch = items_list[i:i+batch_size]
        tasks = [check_and_report(i + j, val) for j, val in enumerate(batch)]
        await asyncio.gather(*tasks)
        
        # Atualiza status após cada lote
        percent = min(100, int(((i + batch_size) / total) * 100))
        try:
            await status_msg.edit_text(f"🚀 VELOCIDADE MÁXIMA: {percent}% ({min(i+batch_size, total)}/{total})\n🎯 Encontrados: {found_count}")
        except: pass
        
        # Pausa reduzida para as APIs respirarem
        await asyncio.sleep(0.5)

    await update.message.reply_text(f"✅ Varredura concluída!\nItens processados: {total}\nSaldos positivos: {found_count}")
    user_pools[user_id] = set()

def add_to_pool(user_id, text):
    if user_id not in user_pools:
        user_pools[user_id] = set()
    
    items = extractor.extract_all(text)
    for it_type, it_val in items:
        user_pools[user_id].add(it_val) 
    return len(items)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    
    user_id = update.effective_user.id
    text = update.message.text
    
    added = add_to_pool(user_id, text)
    if added > 0:
        total = len(user_pools[user_id])
        await update.message.reply_text(f"📥 {added} itens extraídos. Total na fila: {total}. Use /check para iniciar.")
    else:
        await update.message.reply_text("📝 Texto recebido, mas nenhuma Seed/Key foi encontrada.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    
    user_id = update.effective_user.id
    document = update.message.document
    
    if not document.file_name.lower().endswith('.txt'):
        return

    try:
        file = await context.bot.get_file(document.file_id)
        file_content = await file.download_as_bytearray()
        
        try:
            text = file_content.decode('utf-8')
        except UnicodeDecodeError:
            text = file_content.decode('latin-1')
        
        added = add_to_pool(user_id, text)
        total = len(user_pools[user_id])
        
        if added > 0:
            await update.message.reply_text(f"✅ `{document.file_name}`: {added} itens adicionados. Total na fila: {total}.")
            
    except Exception as e:
        logger.error(f"Erro no arquivo {document.file_name}: {e}")

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("clear", clear_pool))
    application.add_handler(CommandHandler("status", show_status))
    application.add_handler(CommandHandler("check", check_pool))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    try:
        logger.info("Bot Master iniciado...")
        application.run_polling()
    except Exception as e:
        logger.critical(f"ERRO FATAL NA INICIALIZAÇÃO: {e}", exc_info=True)

if __name__ == "__main__":
    main()
