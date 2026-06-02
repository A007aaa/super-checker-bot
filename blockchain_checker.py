import asyncio
import aiohttp
import json
import logging
import random
import time
from mnemonic import Mnemonic
from eth_account import Account

# Habilitar recursos de HD Wallet para eth-account
Account.enable_unaudited_hdwallet_features()

logger = logging.getLogger(__name__)

# Configurações de Performance
REQUEST_TIMEOUT = 10
MAX_CONCURRENT_REQUESTS = 40
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

RPC_URLS = {
    "BSC": ["https://bnb-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8", "https://bsc-dataseed.binance.org/"],
    "POLYGON": ["https://polygon-rpc.com/"],
    "ETH": ["https://eth-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8", "https://cloudflare-eth.com/"]
}

semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def _rpc_call(session, urls, method, params):
    async with semaphore:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        for url in urls:
            try:
                async with session.post(url, json=payload, timeout=REQUEST_TIMEOUT) as res:
                    if res.status == 200:
                        data = await res.json()
                        if 'result' in data: return data
            except: continue
        return None

async def check_evm_full(session, addr):
    results = []
    for net in ["ETH", "BSC", "POLYGON"]:
        urls = RPC_URLS.get(net)
        data = await _rpc_call(session, urls, "eth_getBalance", [addr, "latest"])
        if data and 'result' in data:
            try:
                bal = int(data['result'], 16) / 10**18
                if bal > 0: results.append((net, addr, bal))
            except: pass
    return results

async def check_balance_all(seed_phrase):
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            # Gerar endereço EVM de forma compatível
            acc = Account.from_mnemonic(seed_phrase)
            addr = acc.address
            
            found = await check_evm_full(session, addr)
            if found:
                return seed_phrase, found
    except Exception as e:
        logger.error(f"Erro na verificação: {e}")
    return None
