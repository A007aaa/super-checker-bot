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

# Configurações do Bot - RECOMENDADO USAR VARIÁVEIS DE AMBIENTE
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8785377732:AAGgt1tT7eFDzJnaQKISrgKHP7k3C5M4nBs")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "8422682029"))

extractor = SeedExtractor()
user_pools = {}

async def is_authorized(update: Update) -> bool:
    """Verifica se o usuário está autorizado."""
    if not update.effective_user:
        return False
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        logger.warning(f"Acesso negado para o usuário: {user_id}")
        if update.message:
            await update.message.reply_text("⛔ **ACESSO NEGADO.** Este bot é privado.")
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    await update.message.reply_text(
        "🔥 **MODO MASTER ATIVADO!** 🔥\n"
        "Detectando Seeds, Chaves Privadas Solana e ETH.\n"
        "Foco: BTC, ETH, SOL, ADA, USDT, TRON.\n\n"
        "Envie o texto e use /check para processar a memória ou envie e o bot processará automaticamente."
    )

async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    user_id = update.effective_user.id
    user_pools[user_id] = []
    await update.message.reply_text("🗑️ Memória limpa.")

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    
    user_id = update.effective_user.id
    pool_content = user_pools.get(user_id, [])
    
    if not pool_content:
        await update.message.reply_text("❌ Nada para verificar na memória.")
        return

    full_text = " ".join(pool_content)
    items = extractor.extract_all(full_text)
    total = len(items)

    if total == 0:
        await update.message.reply_text("❌ Nenhum item (Seed/Key) encontrado no texto enviado.")
        return

    status_msg = await update.message.reply_text(f"🔍 Analisando {total} itens encontrados...")
    found_count = 0

    for i, (item_type, val) in enumerate(items):
        try:
            res = await check_balance_master(item_type, val)
            if res:
                found_count += 1
                seed_val, balances = res
                msg = f"🎯 **SALDO ENCONTRADO!** ({item_type})\n`{seed_val}`\n"
                for coin, addr, bal in balances:
                    msg += f"• {coin}: {bal} (Endereço: `{addr}`)\n"
                await update.message.reply_text(msg)
        except Exception as e:
            logger.error(f"Erro ao verificar {item_type}: {e}")
        
        if (i + 1) % 5 == 0:
            await status_msg.edit_text(f"🔍 Progresso: {i+1}/{total} | 🎯 Achados: {found_count}")

    await update.message.reply_text(f"✅ Varredura concluída!\nItens processados: {total}\nSaldos positivos: {found_count}")
    # Limpa o pool após a verificação
    user_pools[user_id] = []

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update):
        return
    
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id not in user_pools:
        user_pools[user_id] = []
    
    user_pools[user_id].append(text)
    
    # Opcional: Auto-check se encontrar algo importante imediatamente
    items = extractor.extract_all(text)
    if items:
        await update.message.reply_text(f"📥 {len(items)} itens detectados e salvos. Use /check para analisar.")
    else:
        await update.message.reply_text("📝 Texto adicionado à memória. Continue enviando ou use /check.")

async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN não configurado!")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("clear", clear_pool))
    application.add_handler(CommandHandler("check", check_pool))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot iniciado...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Mantém rodando
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
