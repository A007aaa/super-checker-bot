import os
import logging
import tempfile
import time
import asyncio
import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from blockchain_checker import check_balance_all
from seed_extractor import SeedExtractor

# ── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
# Silence overly verbose libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
# ─────────────────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8785377732:AAGEOY6H0Bo_mgvbymAJ-vWdmH08GMIQGnM')

user_buffers = {}
BATCH_WAIT_TIME = 10
MAX_FILE_SIZE = 50 * 1024 * 1024
extractor = SeedExtractor()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Captura todas as exceções do dispatcher e loga sem derrubar o bot."""
    error = context.error

    if isinstance(error, telegram.error.Conflict):
        logger.warning(
            "Conflict: outra instância do bot está rodando. "
            "Certifique-se de que apenas uma instância está ativa. "
            "Esta instância continuará tentando. Erro: %s", error
        )
        return

    if isinstance(error, telegram.error.NetworkError):
        logger.warning("Erro de rede (será retentado automaticamente): %s", error)
        return

    if isinstance(error, telegram.error.TimedOut):
        logger.warning("Timeout na requisição ao Telegram (será retentado): %s", error)
        return

    if isinstance(error, telegram.error.RetryAfter):
        logger.warning("Rate limit atingido. Aguardando %.1f s: %s", error.retry_after, error)
        return

    # Para qualquer outro erro, loga com traceback completo
    logger.error("Exceção não tratada no handler:", exc_info=context.error)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Comando /start recebido de chat_id=%s", update.effective_chat.id)
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
        try:
            await asyncio.sleep(BATCH_WAIT_TIME)
            all_text = "\n".join(buffer['contents'])
            del user_buffers[chat_id]

            seeds = extractor.extract_all_seeds(all_text)
            logger.info("chat_id=%s: %d seed(s) extraída(s) para processamento", chat_id, len(seeds))

            if not seeds:
                await context.bot.send_message(chat_id=chat_id, text="❌ Nenhuma seed válida encontrada.")
                return

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⏳ Processando {len(seeds)} seeds em múltiplas blockchains...\n\n⏱️ Isso pode levar alguns minutos..."
            )

            semaphore = asyncio.Semaphore(10)

            async def check_with_semaphore(seed):
                async with semaphore:
                    return await check_balance_all(seed)

            tasks = [check_with_semaphore(seed) for seed in seeds]
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=300,  # 5 min hard cap para o lote inteiro
                )
            except asyncio.TimeoutError:
                logger.warning("chat_id=%s: timeout ao processar lote de seeds", chat_id)
                results = []

            positivos = [r for r in results if r is not None and not isinstance(r, Exception)]
            logger.info("chat_id=%s: %d resultado(s) positivo(s) encontrado(s)", chat_id, len(positivos))

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

        except asyncio.CancelledError:
            logger.info("chat_id=%s: tarefa de lote cancelada (nova mensagem recebida)", chat_id)
        except Exception as exc:
            logger.error("chat_id=%s: erro inesperado ao processar lote: %s", chat_id, exc, exc_info=True)
            try:
                await context.bot.send_message(chat_id=chat_id, text="❌ Erro interno ao processar seeds. Tente novamente.")
            except Exception:
                pass

    buffer['timer'] = asyncio.create_task(run_task())

async def add_to_buffer(chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    if chat_id not in user_buffers:
        user_buffers[chat_id] = {'contents': [], 'timer': None}
    user_buffers[chat_id]['contents'].append(text)
    await process_batch(chat_id, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text:
        chat_id = update.effective_chat.id
        logger.info("chat_id=%s: mensagem de texto recebida (%d chars)", chat_id, len(update.message.text))
        await add_to_buffer(chat_id, update.message.text, context)
        await update.message.reply_text("✅ Adicionado ao lote...")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    chat_id = update.effective_chat.id
    logger.info("chat_id=%s: documento recebido '%s' (%s bytes)",
                chat_id, document.file_name, document.file_size)

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
    logger.info("Iniciando Bot Multi-Blockchain...")
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Handlers de mensagens
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Error handler global — captura Conflict, NetworkError, etc. sem derrubar o bot
    application.add_error_handler(error_handler)

    logger.info("🚀 Bot Multi-Blockchain rodando...")
    application.run_polling(
        drop_pending_updates=True,   # descarta updates acumulados ao reiniciar
        allowed_updates=Update.ALL_TYPES,
    )

if __name__ == "__main__":
    main()
