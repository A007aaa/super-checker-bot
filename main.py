
import os
import requests
import hashlib
import tempfile
import re
import time
import asyncio
from multiprocessing import Pool, cpu_count
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Bibliotecas de Derivação HD
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins, Bip84, Bip84Coins, Bip39MnemonicValidator
)

# Configurações do Bot do Telegram
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8785377732:AAGEOY6H0Bo_mgvbymAJ-vWdmH08GMIQGnM')

user_buffers = {}
BATCH_WAIT_TIME = 5 

def get_addresses(seed_phrase):
    """Gera endereços usando os padrões BIP44, BIP49 e BIP84 para máxima compatibilidade."""
    try:
        seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
        addresses = []

        # 1. Bitcoin (BTC) - Testa 3 formatos: Legado, SegWit e Native SegWit
        # Legado (BIP44)
        btc_bip44 = Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
        addresses.append(('BTC (Legacy)', btc_bip44.PublicKey().ToAddress()))
        
        # SegWit (BIP49)
        btc_bip49 = Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
        addresses.append(('BTC (SegWit)', btc_bip49.PublicKey().ToAddress()))
        
        # Native SegWit (BIP84 - bech32)
        btc_bip84 = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
        addresses.append(('BTC (Native SegWit)', btc_bip84.PublicKey().ToAddress()))

        # 2. Ethereum (ETH) - BIP44
        eth_bip44 = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
        addresses.append(('ETH', eth_bip44.PublicKey().ToAddress()))

        # 3. Tron (TRX) - BIP44
        trx_bip44 = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
        addresses.append(('TRX', trx_bip44.PublicKey().ToAddress()))

        # 4. Solana (SOL) - BIP44
        sol_bip44 = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
        addresses.append(('SOL', sol_bip44.PublicKey().ToAddress()))

        return addresses
    except:
        return []

def check_balance_all(seed):
    seed = seed.strip()
    if not seed: return None
    
    # Validar se a seed é válida
    try:
        if not Bip39MnemonicValidator().IsValid(seed):
            return None
    except:
        return None
        
    generated_addresses = get_addresses(seed)
    if not generated_addresses: return None
    
    found = []
    
    for label, addr in generated_addresses:
        try:
            # BTC
            if 'BTC' in label:
                res = requests.get(f"https://blockchain.info/balance?active={addr}", timeout=5).json()
                bal = res.get(addr, {}).get("final_balance", 0) / 10**8
                if bal > 0: found.append((label, addr, bal))
            
            # ETH & USDT (ERC20)
            elif 'ETH' in label:
                res_eth = requests.get(f"https://api.blockcypher.com/v1/eth/main/addrs/{addr}/balance", timeout=5).json()
                bal_eth = res_eth.get("balance", 0) / 10**18
                if bal_eth > 0: found.append(("ETH", addr, bal_eth))
                
                # USDT ERC20
                res_tokens = requests.get(f"https://api.ethplorer.io/getAddressInfo/{addr}?apiKey=freekey", timeout=5).json()
                if 'tokens' in res_tokens:
                    for t in res_tokens['tokens']:
                        if t['tokenInfo']['symbol'] == 'USDT':
                            bal_usdt = float(t['balance']) / (10**int(t['tokenInfo']['decimals']))
                            if bal_usdt > 0: found.append(("USDT (ERC20)", addr, bal_usdt))

            # TRX & USDT (TRC20)
            elif 'TRX' in label:
                res_trx = requests.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=5).json()
                if res_trx.get('data'):
                    bal_trx = res_trx['data'][0].get('balance', 0) / 10**6
                    if bal_trx > 0: found.append(("TRX", addr, bal_trx))
                    
                    trc20_balances = res_trx['data'][0].get('trc20', [])
                    for token in trc20_balances:
                        if 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' in token:
                            bal_usdt = float(token['TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t']) / 10**6
                            if bal_usdt > 0: found.append(("USDT (TRC20)", addr, bal_usdt))

            # SOL
            elif 'SOL' in label:
                payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
                res_sol = requests.post("https://api.mainnet-beta.solana.com", json=payload, timeout=5).json()
                bal_sol = res_sol.get('result', {}).get('value', 0) / 10**9
                if bal_sol > 0: found.append(("SOL", addr, bal_sol))
        except:
            pass

    if found:
        return (seed, found)
    return None

def extract_seeds(text):
    words = re.findall(r'\b[a-z]+\b', text.lower())
    potential_seeds = []
    lengths = [24, 21, 18, 15, 12]
    
    # Carregar lista de palavras BIP39 para filtro rápido
    from mnemonic import Mnemonic
    bip39_list = set(Mnemonic("english").wordlist)
    
    for length in lengths:
        for i in range(len(words) - length + 1):
            segment = words[i:i+length]
            if all(word in bip39_list for word in segment):
                seed = " ".join(segment)
                if seed not in potential_seeds:
                    potential_seeds.append(seed)
    return potential_seeds

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('Bot HD Wallet Checker Ativo!\nEnvie seeds ou arquivos. Verifico BTC (3 formatos), ETH, TRX, SOL e USDT.')

async def process_batch(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    if chat_id not in user_buffers: return
    buffer = user_buffers[chat_id]
    if buffer['timer']: buffer['timer'].cancel()

    async def run_task():
        await asyncio.sleep(BATCH_WAIT_TIME)
        all_text = "\n".join(buffer['contents'])
        del user_buffers[chat_id]
        seeds = extract_seeds(all_text)
        if not seeds:
            await context.bot.send_message(chat_id=chat_id, text="Nenhuma seed válida encontrada.")
            return
        
        await context.bot.send_message(chat_id=chat_id, text=f"Processando {len(seeds)} seeds com tecnologia HD Wallet...")
        with Pool(cpu_count()) as p:
            results = p.map(check_balance_all, seeds)
        
        positivos = [r for r in results if r is not None]
        response = ["--- RELATÓRIO FINAL ---", f"Seeds testadas: {len(seeds)}", f"Saldos encontrados: {len(positivos)}", "="*20]
        
        if positivos:
            for seed, found_list in positivos:
                msg = f"!!! CARTEIRA COM SALDO !!!\nSeed: {seed}\n"
                for coin, addr, bal in found_list:
                    msg += f"• {coin}: {bal}\n  Endereço: {addr}\n"
                response.append(msg)
        else:
            response.append("Nenhum saldo detectado.")
            
        final_msg = "\n".join(response)
        if len(final_msg) > 4000:
            for i in range(0, len(final_msg), 4000):
                await context.bot.send_message(chat_id=chat_id, text=final_msg[i:i+4000])
        else:
            await context.bot.send_message(chat_id=chat_id, text=final_msg)

    buffer['timer'] = asyncio.create_task(run_task())

async def add_to_buffer(chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    if chat_id not in user_buffers: user_buffers[chat_id] = {'contents': [], 'timer': None}
    user_buffers[chat_id]['contents'].append(text)
    await process_batch(chat_id, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text:
        await add_to_buffer(update.effective_chat.id, update.message.text, context)
        await update.message.reply_text("Adicionado...")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    file_id = document.file_id
    new_file = await context.bot.get_file(file_id)
    temp_path = os.path.join(tempfile.gettempdir(), f"tmp_{int(time.time())}")
    try:
        await new_file.download_to_drive(temp_path)
        with open(temp_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        await add_to_buffer(update.effective_chat.id, content, context)
        await update.message.reply_text(f"'{document.file_name}' adicionado...")
    finally:
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    print("Bot rodando...")
    application.run_polling()

if __name__ == "__main__":
    main()
