import os
import logging
import tempfile
import asyncio
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_balance_master
from seed_extractor import SeedExtractor

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurações do Bot
TELEGRAM_BOT_TOKEN = "8785377732:AAGgt1tT7eFDzJnaQKISrgKHP7k3C5M4nBs"
ALLOWED_USER_ID = 8422682029  # Trava de segurança: apenas este ID pode usar o bot

extractor = SeedExtractor()
user_pools = {}

async def is_authorized(update: Update) -> bool:
    """Verifica se o usuário está autorizado."""
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        logger.warning(f"Acesso negado para o usuário: {user_id}")
        await update.message.reply_text("⛔ **ACESSO NEGADO.** Este bot é privado.")
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update): return
    await update.message.reply_text("🔥 **MODO MASTER ATIVADO!** 🔥\nDetectando Seeds, Chaves Privadas Solana e ETH.\nFoco: BTC, ETH, SOL, ADA, USDT, TRON.\n\nEnvie o texto e use /check.")

async def clear_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update): return
    user_pools[update.effective_user.id] = []
    await update.message.reply_text("🗑️ Memória limpa.")

async def check_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update): return
    user_id = update.effective_user.id
    text = " ".join(user_pools.get(user_id, []))
    if not text:
        await update.message.reply_text("❌ Nada para verificar.")
        return

    items = extractor.extract_all(text)
    total = len(items)
    if total == 0:
        await update.message.reply_text("❌ Nenhum item (Seed/Key) encontrado no texto enviado.")
        return

    status = await update.message.reply_text(f"🔍 Analisando {total} itens encontrados...")

    found_count = 0
    for i, (type, val) in enumerate(items):
        try:
            res = await check_balance_master(type, val)
            if res:
                found_count += 1
                v, found = res
                msg = f"🎯 **SALDO ENCONTRADO!** ({type})\n`{v}`\n"
                for c, a, b in found: msg += f"• {c}: {b}\n"
                await update.message.reply_text(msg)
        except Exception as e:
            logger.error(f"Erro ao verificar {type}: {e}")
        
        if i % 10 == 0 and i > 0:
            await status.edit_text(f"🔍 Progresso: {i+1}/{total} | 🎯 Achados: {found_count}")

    await update.message.reply_text(f"✅ Fim da varredura! Itens: {total} | Achados: {found_count}")

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_authorized(update): return
    user_id = update.effective_user.id
    if user_id not in user_pools: user_pools[user_id] = []
    
    text = ""
    if update.message.document:
        file = await context.bot.get_file(update.message.document.file_id)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            with open(tmp.name, 'r', encoding='utf-8', errors='ignore') as f: text = f.read()
        os.unlink(tmp.name)
    else: text = update.message.text

    if text:
        user_pools[user_id].append(text)
        await update.message.reply_text(f"📥 Recebido. (Total acumulado: {len(user_pools[user_id])} mensagens)")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_pool))
    app.add_handler(CommandHandler("clear", clear_pool))
    app.add_handler(MessageHandler(filters.TEXT | filters.Document.ALL, handle_input))
    
    print("Bot iniciado com trava de segurança...")
    app.run_polling()

if __name__ == "__main__": main()
