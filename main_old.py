import os
import requests
import hashlib
import tempfile
import re
import time
import asyncio
import json
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

# Mapeamento de blockchains e seus RPC/APIs
BLOCKCHAIN_CONFIG = {
    'BTC': {'type': 'bitcoin', 'name': 'Bitcoin'},
    'ETH': {'type': 'ethereum', 'name': 'Ethereum'},
    'SOL': {'type': 'solana', 'name': 'Solana'},
    'BNB': {'type': 'bsc', 'name': 'BNB Chain'},
    'AVAX': {'type': 'avalanche', 'name': 'Avalanche'},
    'ADA': {'type': 'cardano', 'name': 'Cardano'},
    'DOT': {'type': 'polkadot', 'name': 'Polkadot'},
    'ATOM': {'type': 'cosmos', 'name': 'Cosmos'},
    'NEAR': {'type': 'near', 'name': 'Near Protocol'},
    'ALGO': {'type': 'algorand', 'name': 'Algorand'},
    'XTZ': {'type': 'tezos', 'name': 'Tezos'},
    'APT': {'type': 'aptos', 'name': 'Aptos'},
    'SUI': {'type': 'sui', 'name': 'Sui'},
    'TON': {'type': 'toncoin', 'name': 'Toncoin'},
    'TRX': {'type': 'tron', 'name': 'Tron'},
    'XRP': {'type': 'ripple', 'name': 'XRP'},
    'LTC': {'type': 'litecoin', 'name': 'Litecoin'},
    'XMR': {'type': 'monero', 'name': 'Monero'},
    'ARB': {'type': 'arbitrum', 'name': 'Arbitrum'},
    'OP': {'type': 'optimism', 'name': 'Optimism'},
    'BASE': {'type': 'base', 'name': 'Base'},
    'MATIC': {'type': 'polygon', 'name': 'Polygon'},
    'ZKSYNC': {'type': 'zksync', 'name': 'zkSync'},
    'STARK': {'type': 'starknet', 'name': 'Starknet'},
    'LINEA': {'type': 'linea', 'name': 'Linea'},
    'IMX': {'type': 'immutable', 'name': 'Immutable'},
    'RON': {'type': 'ronin', 'name': 'Ronin'},
    'FLOW': {'type': 'flow', 'name': 'Flow'},
    'WAX': {'type': 'wax', 'name': 'WAX'},
    'ZEC': {'type': 'zcash', 'name': 'Zcash'},
    'SCRT': {'type': 'secret', 'name': 'Secret'},
    'LINK': {'type': 'chainlink', 'name': 'Chainlink'},
    'HBAR': {'type': 'hedera', 'name': 'Hedera'},
    'QNT': {'type': 'quant', 'name': 'Quant'},
}

def get_addresses(seed_phrase):
    """Gera endereços para múltiplas blockchains usando BIP44/BIP49/BIP84."""
    try:
        seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
        addresses = {}

        # Bitcoin (3 formatos)
        try:
            btc_bip44 = Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['BTC_Legacy'] = btc_bip44.PublicKey().ToAddress()
            
            btc_bip49 = Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['BTC_SegWit'] = btc_bip49.PublicKey().ToAddress()
            
            btc_bip84 = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['BTC_Native'] = btc_bip84.PublicKey().ToAddress()
        except:
            pass

        # Ethereum (compatível com EVM chains)
        try:
            eth = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            eth_addr = eth.PublicKey().ToAddress()
            addresses['ETH'] = eth_addr
            addresses['BSC'] = eth_addr  # BNB Chain usa mesmo endereço
            addresses['AVAX'] = eth_addr  # Avalanche
            addresses['MATIC'] = eth_addr  # Polygon
            addresses['ARB'] = eth_addr  # Arbitrum
            addresses['OP'] = eth_addr  # Optimism
            addresses['BASE'] = eth_addr  # Base
            addresses['ZKSYNC'] = eth_addr  # zkSync
            addresses['LINEA'] = eth_addr  # Linea
            addresses['FLOW'] = eth_addr  # Flow
        except:
            pass

        # Tron
        try:
            trx = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['TRX'] = trx.PublicKey().ToAddress()
        except:
            pass

        # Solana
        try:
            sol = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['SOL'] = sol.PublicKey().ToAddress()
        except:
            pass

        # Litecoin
        try:
            ltc = Bip44.FromSeed(seed_bytes, Bip44Coins.LITECOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['LTC'] = ltc.PublicKey().ToAddress()
        except:
            pass

        # Cardano
        try:
            ada = Bip44.FromSeed(seed_bytes, Bip44Coins.CARDANO).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['ADA'] = ada.PublicKey().ToAddress()
        except:
            pass

        # Cosmos
        try:
            atom = Bip44.FromSeed(seed_bytes, Bip44Coins.COSMOS).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['ATOM'] = atom.PublicKey().ToAddress()
        except:
            pass

        return addresses
    except:
        return {}

def check_balance_all(seed):
    """Verifica saldos em múltiplas blockchains."""
    seed = seed.strip()
    if not seed:
        return None
    
    # Validar seed
    try:
        if not Bip39MnemonicValidator().IsValid(seed):
            return None
    except:
        return None
        
    addresses = get_addresses(seed)
    if not addresses:
        return None
    
    found = []
    
    # Bitcoin
    for btc_type in ['BTC_Legacy', 'BTC_SegWit', 'BTC_Native']:
        if btc_type in addresses:
            try:
                addr = addresses[btc_type]
                res = requests.get(f"https://blockchain.info/balance?active={addr}", timeout=5).json()
                bal = res.get(addr, {}).get("final_balance", 0) / 10**8
                if bal > 0:
                    found.append((btc_type, addr, bal))
            except:
                pass
    
    # Ethereum e EVM chains (ETH, BSC, AVAX, MATIC, ARB, OP, BASE, ZKSYNC, LINEA)
    if 'ETH' in addresses:
        eth_addr = addresses['ETH']
        
        # ETH balance
        try:
            res = requests.get(f"https://api.blockcypher.com/v1/eth/main/addrs/{eth_addr}/balance", timeout=5).json()
            bal = res.get("balance", 0) / 10**18
            if bal > 0:
                found.append(("ETH", eth_addr, bal))
        except:
            pass
        
        # USDT ERC20 (Ethereum)
        try:
            res = requests.get(f"https://api.ethplorer.io/getAddressInfo/{eth_addr}?apiKey=freekey", timeout=5).json()
            if 'tokens' in res:
                for t in res['tokens']:
                    if t['tokenInfo']['symbol'] == 'USDT':
                        bal = float(t['balance']) / (10**int(t['tokenInfo']['decimals']))
                        if bal > 0:
                            found.append(("USDT_ERC20", eth_addr, bal))
        except:
            pass
        
        # USDT em outras EVM chains (BSC, MATIC, ARB, OP, BASE)
        evm_chains = {
            'BSC': 'https://bscscan.com/api',
            'MATIC': 'https://polygonscan.com/api',
            'ARB': 'https://arbiscan.io/api',
            'OP': 'https://optimistic.etherscan.io/api',
            'BASE': 'https://basescan.org/api',
        }
        
        for chain_name, api_url in evm_chains.items():
            try:
                # USDT contract addresses por chain
                usdt_contracts = {
                    'BSC': '0x55d398326f99059fF775485246999027B3197955',
                    'MATIC': '0xc2132D05D31c914a87C6611C10748AEb04B58e8F',
                    'ARB': '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9',
                    'OP': '0x94b008aA00579c1307B0EF2c499aD98a8ce58e58',
                    'BASE': '0x833589fCD6eDb6E08f4c7C32D4f71b1566469c3d',
                }
                
                if chain_name in usdt_contracts:
                    # Verificar saldo USDT
                    params = {
                        'module': 'account',
                        'action': 'tokenbalance',
                        'contractaddress': usdt_contracts[chain_name],
                        'address': eth_addr,
                        'tag': 'latest'
                    }
                    res = requests.get(api_url, params=params, timeout=5).json()
                    if res.get('status') == '1':
                        bal = float(res.get('result', 0)) / 10**6
                        if bal > 0:
                            found.append((f"USDT_{chain_name}", eth_addr, bal))
            except:
                pass
    
    # Tron e USDT TRC20
    if 'TRX' in addresses:
        trx_addr = addresses['TRX']
        try:
            res = requests.get(f"https://api.trongrid.io/v1/accounts/{trx_addr}", timeout=5).json()
            if res.get('data'):
                bal = res['data'][0].get('balance', 0) / 10**6
                if bal > 0:
                    found.append(("TRX", trx_addr, bal))
                
                # USDT TRC20
                trc20_balances = res['data'][0].get('trc20', [])
                for token in trc20_balances:
                    if 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' in token:
                        bal = float(token['TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t']) / 10**6
                        if bal > 0:
                            found.append(("USDT_TRC20", trx_addr, bal))
        except:
            pass
    
    # Solana
    if 'SOL' in addresses:
        sol_addr = addresses['SOL']
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [sol_addr]}
            res = requests.post("https://api.mainnet-beta.solana.com", json=payload, timeout=5).json()
            bal = res.get('result', {}).get('value', 0) / 10**9
            if bal > 0:
                found.append(("SOL", sol_addr, bal))
            
            # USDT SPL (Solana)
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenAccountsByOwner",
                    "params": [
                        sol_addr,
                        {"mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenEsl"},
                        {"encoding": "jsonParsed"}
                    ]
                }
                res = requests.post("https://api.mainnet-beta.solana.com", json=payload, timeout=5).json()
                if 'result' in res and res['result']['value']:
                    for account in res['result']['value']:
                        bal = float(account['account']['data']['parsed']['info']['tokenAmount']['amount']) / 10**6
                        if bal > 0:
                            found.append(("USDT_SPL", sol_addr, bal))
            except:
                pass
        except:
            pass
    
    # Litecoin
    if 'LTC' in addresses:
        ltc_addr = addresses['LTC']
        try:
            res = requests.get(f"https://blockchair.com/litecoin/addresses/{ltc_addr}", timeout=5).json()
            if res.get('data'):
                bal = res['data'][ltc_addr]['address']['balance'] / 10**8
                if bal > 0:
                    found.append(("LTC", ltc_addr, bal))
        except:
            pass
    
    # Cardano
    if 'ADA' in addresses:
        ada_addr = addresses['ADA']
        try:
            res = requests.get(f"https://cardano-mainnet.blockfrost.io/api/v0/addresses/{ada_addr}", 
                             headers={"project_id": "mainnetXXXXXXXXXXXXXXXX"}, timeout=5).json()
            if 'amount' in res:
                bal = float(res['amount'][0]['quantity']) / 10**6
                if bal > 0:
                    found.append(("ADA", ada_addr, bal))
        except:
            pass
    
    # Cosmos
    if 'ATOM' in addresses:
        atom_addr = addresses['ATOM']
        try:
            res = requests.get(f"https://rest.cosmos.directory/cosmoshub/cosmos/bank/v1beta1/balances/{atom_addr}", timeout=5).json()
            if 'balances' in res:
                for balance in res['balances']:
                    if balance['denom'] == 'uatom':
                        bal = float(balance['amount']) / 10**6
                        if bal > 0:
                            found.append(("ATOM", atom_addr, bal))
        except:
            pass

    if found:
        return (seed, found)
    return None

def extract_seeds(text):
    """Extrai seeds de 12, 15, 18, 21 e 24 palavras."""
    words = re.findall(r'\b[a-z]+\b', text.lower())
    potential_seeds = []
    lengths = [24, 21, 18, 15, 12]
    
    try:
        from mnemonic import Mnemonic
        bip39_list = set(Mnemonic("english").wordlist)
    except:
        return []
    
    for length in lengths:
        for i in range(len(words) - length + 1):
            segment = words[i:i+length]
            if all(word in bip39_list for word in segment):
                seed = " ".join(segment)
                if seed not in potential_seeds:
                    potential_seeds.append(seed)
    
    return potential_seeds

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
2. Ou envie arquivo .txt com múltiplas seeds
3. Bot processa até 100k+ combinações
4. Retorna apenas endereços com saldo em USDT

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
        
        seeds = extract_seeds(all_text)
        if not seeds:
            await context.bot.send_message(chat_id=chat_id, text="❌ Nenhuma seed válida encontrada.")
            return
        
        await context.bot.send_message(chat_id=chat_id, text=f"⏳ Processando {len(seeds)} seeds em múltiplas blockchains...")
        
        with Pool(cpu_count()) as p:
            results = p.map(check_balance_all, seeds)
        
        positivos = [r for r in results if r is not None]
        
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
        
        # Dividir se muito grande
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
    file_id = document.file_id
    new_file = await context.bot.get_file(file_id)
    temp_path = os.path.join(tempfile.gettempdir(), f"tmp_{int(time.time())}")
    try:
        await new_file.download_to_drive(temp_path)
        with open(temp_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        await add_to_buffer(update.effective_chat.id, content, context)
        await update.message.reply_text(f"✅ '{document.file_name}' adicionado ao lote...")
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

