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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🚀 **Super Checker Verboso Ativado!**\n\nAgora eu vou te avisar sobre cada seed que eu encontrar, mesmo que o saldo seja zero, para você saber que estou trabalhando.")

async def process_single_seed(seed, update):
    # Validar a seed antes de testar saldo
    is_valid, reason = extractor.check_seed(seed)
    if not is_valid:
        await update.message.reply_text(f"⚠️ **Seed Inválida:** `{seed[:20]}...`\nMotivo: {reason}")
        return False

    try:
        res = await check_balance_all(seed)
        if res:
            seed, found = res
            msg = f"🎯 **SALDO ENCONTRADO!**\n\n🔑 **Seed:** `{seed}`\n"
            for c, a, b in found:
                msg += f"• {c}: {b} (Addr: `{a}`)\n"
            await update.message.reply_text(msg, parse_mode='Markdown')
            return True
        else:
            # Feedback mesmo se não houver saldo (apenas para mensagens diretas)
            await update.message.reply_text(f"✅ Seed lida: `{seed[:15]}...` | Saldo: 0")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao processar `{seed[:15]}...`: {str(e)}")
    return False

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    status_msg = await update.message.reply_text("⏳ Baixando e extraindo seeds...")
    file = await context.bot.get_file(doc.file_id)
    
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        with open(tmp.name, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    os.unlink(tmp.name)

    seeds = extractor.extract_all_seeds(content)
    total = len(seeds)
    await status_msg.edit_text(f"📦 Encontradas {total} seeds. Iniciando verificação...")

    found_count = 0
    for i, seed in enumerate(seeds):
        # Para arquivos grandes, não enviamos mensagem de "saldo 0" para cada uma para não ser banido pelo Telegram
        res = await check_balance_all(seed)
        if res:
            found_count += 1
            seed, found = res
            msg = f"🎯 **ACHADO NO ARQUIVO!**\nSeed: `{seed}`\n"
            for c, a, b in found: msg += f"• {c}: {b}\n"
            await update.message.reply_text(msg, parse_mode='Markdown')
        
        if (i + 1) % 10 == 0:
            await status_msg.edit_text(f"⏳ Progresso: {i+1}/{total} | Encontradas: {found_count}")

    await update.message.reply_text(f"✅ Fim do arquivo. Total: {total} | Encontradas: {found_count}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    seeds = extractor.extract_all_seeds(update.message.text)
    if not seeds:
        await update.message.reply_text("❌ Nenhuma seed válida encontrada no texto.")
        return
    for seed in seeds:
        await process_single_seed(seed, update)

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()
