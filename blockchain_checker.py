import asyncio
import aiohttp
import json
import logging
import random
import time
import hmac
import hashlib
import base64
from mnemonic import Mnemonic

# Bibliotecas leves e pré-compiladas (compatíveis com Windows)
from eth_account import Account
Account.enable_unaudited_hdwallet_features()

logger = logging.getLogger(__name__)

# ── ULTRA SPEED & ASSERTIVENESS TUNABLES ────────────────────────────────────
REQUEST_TIMEOUT   = 10
MAX_CONCURRENT_REQUESTS = 40
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

RPC_URLS = {
    "BSC": ["https://bnb-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8", "https://bsc-dataseed.binance.org/"],
    "POLYGON": ["https://polygon-rpc.com/"],
    "ETH": ["https://eth-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8", "https://cloudflare-eth.com/"],
    "SOL": ["https://solana-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8", "https://api.mainnet-beta.solana.com"],
    "ARBITRUM": ["https://arb1.arbitrum.io/rpc"],
    "OPTIMISM": ["https://mainnet.optimism.io"],
    "AVALANCHE": ["https://api.avax.network/ext/bc/C/rpc"],
    "FANTOM": ["https://rpc.ftm.tools/"]
}

USDT_CONTRACTS = {
    "ETH": "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "BSC": "0x55d398326f99059ff775485246999027b3197955",
    "POLYGON": "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"
}

semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
rpc_blacklist = {}
balance_cache = {}

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

async def get_universal_addresses(seed_phrase):
    addr_map = []
    try:
        # EVM (ETH, BSC, etc) usando eth-account (Leve)
        acc = Account.from_mnemonic(seed_phrase)
        addr_map.append(("EVM", "ADDR", acc.address))
        
        # Para Solana e Tron, usaremos uma implementação simplificada ou fallbacks
        # para evitar a biblioteca bip-utils que quebra no Windows.
    except Exception as e:
        logger.error(f"Erro ao gerar endereços: {e}")
    return addr_map

async def check_evm_full(session, addr):
    results = []
    for net in ["ETH", "BSC", "POLYGON"]:
        urls = RPC_URLS.get(net)
        data = await _rpc_call(session, urls, "eth_getBalance", [addr, "latest"])
        if data and 'result' in data:
            bal = int(data['result'], 16) / 10**18
            if bal > 0: results.append((net, addr, bal))
    return results

async def check_balance_all(seed_phrase):
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        addrs = await get_universal_addresses(seed_phrase)
        found = []
        for coin, type, addr in addrs:
            if coin == "EVM":
                res = await check_evm_full(session, addr)
                if res: found.extend(res)
        if found: return seed_phrase, found
    return None
