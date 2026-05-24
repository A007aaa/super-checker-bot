import asyncio
import aiohttp
import json
import logging
import random

logger = logging.getLogger(__name__)
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins, Bip84, Bip84Coins, Bip39MnemonicValidator,
    Bip32Utils, SolAddr
)

# ── Configurações de Varredura Profunda ────────────────────────────────────
REQUEST_TIMEOUT   = 10          
SEED_TIMEOUT      = 150         
MAX_CONCURRENT_REQUESTS = 60    
GAP_LIMIT = 10                  # Aumentado para busca exaustiva
MAX_ACCOUNTS = 3                # Aumentado para busca exaustiva
MIN_BALANCE_THRESHOLD = 1e-10   # Filtro para ignorar saldos "zero" reais, mas pegar poeira
# ────────────────────────────────────────────────────────────────────────────

semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

RPC_URLS = {
    "BSC": ["https://bsc-dataseed.binance.org/", "https://bsc-dataseed1.defibit.io/"],
    "POLYGON": ["https://polygon-rpc.com/", "https://rpc-mainnet.maticvigil.com/"],
    "ETH": ["https://cloudflare-eth.com/", "https://eth-mainnet.public.blastapi.io"],
    "ARBITRUM": ["https://arb1.arbitrum.io/rpc"],
    "OPTIMISM": ["https://mainnet.optimism.io"],
    "BASE": ["https://mainnet.base.org"],
    "AVALANCHE": ["https://api.avax.network/ext/bc/C/rpc"],
    "FANTOM": ["https://rpc.ftm.tools/"]
}

async def _rpc_call(session, urls, method, params):
    async with semaphore:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        random.shuffle(urls)
        for url in urls:
            try:
                async with session.post(url, json=payload, timeout=REQUEST_TIMEOUT) as res:
                    if res.status == 200:
                        data = await res.json()
                        if 'result' in data: return data.get('result')
            except Exception: continue
        return None

async def get_universal_addresses(seed_phrase):
    try:
        seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
    except Exception: return []
    
    addr_map = []
    for acc in range(MAX_ACCOUNTS):
        for idx in range(GAP_LIMIT):
            # BTC (Native, P2SH, Legacy)
            try:
                addr_map.append(("BTC", "Native", Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(acc).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx).PublicKey().ToAddress()))
                addr_map.append(("BTC", "P2SH", Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(acc).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx).PublicKey().ToAddress()))
                addr_map.append(("BTC", "Legacy", Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(acc).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx).PublicKey().ToAddress()))
            except Exception: pass

            # EVM
            try:
                eth_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(acc).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx).PublicKey().ToAddress()
                addr_map.append(("EVM", "ADDR", eth_addr))
            except Exception: pass

            # Solana
            try:
                sol_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(acc).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx)
                sol_addr = SolAddr.Encode(sol_ctx.PublicKey().Raw().ToBytes())
                addr_map.append(("SOL", "ADDR", sol_addr))
            except Exception: pass

            # Tron
            try:
                trx_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(acc).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx).PublicKey().ToAddress()
                addr_map.append(("TRX", "STD", trx_addr))
            except Exception: pass

    return addr_map

async def check_btc(session, addr):
    async with semaphore:
        try:
            async with session.get(f"https://blockchain.info/q/addressbalance/{addr}", timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200:
                    text = await res.text()
                    bal = int(text) / 10**8
                    if bal > MIN_BALANCE_THRESHOLD: return ("BTC", addr, bal)
        except Exception: pass
        return None

async def check_solana(session, addr):
    async with semaphore:
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
            async with session.post("https://api.mainnet-beta.solana.com", json=payload, timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200:
                    data = await res.json()
                    bal = data.get('result', {}).get('value', 0) / 10**9
                    if bal > MIN_BALANCE_THRESHOLD: return ("SOL", addr, bal)
        except Exception: pass
        return None

async def check_evm_full(session, addr):
    results = []
    tasks = []
    keys = list(RPC_URLS.keys())
    for net in keys:
        tasks.append(_rpc_call(session, RPC_URLS[net], "eth_getBalance", [addr, "latest"]))
    
    rpc_res = await asyncio.gather(*tasks)
    for i, res in enumerate(rpc_res):
        if res and res != '0x0':
            try:
                bal = int(res, 16) / 10**18
                if bal > MIN_BALANCE_THRESHOLD: results.append((keys[i], addr, bal))
            except: pass
    return results

async def check_trx(session, addr):
    async with semaphore:
        try:
            async with session.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200:
                    data = await res.json()
                    if data.get('data'):
                        acc = data['data'][0]
                        bal = acc.get('balance', 0) / 10**6
                        if bal > MIN_BALANCE_THRESHOLD: return ("TRX", addr, bal)
        except Exception: pass
        return None

async def check_balance_all(seed):
    seed = seed.strip()
    if not seed: return None
    addr_map = await get_universal_addresses(seed)
    if not addr_map: return None

    async with aiohttp.ClientSession() as session:
        tasks = []
        for coin, label, addr in addr_map:
            if coin == "BTC": tasks.append(check_btc(session, addr))
            elif coin == "EVM": tasks.append(check_evm_full(session, addr))
            elif coin == "TRX": tasks.append(check_trx(session, addr))
            elif coin == "SOL": tasks.append(check_solana(session, addr))
        
        try:
            raw = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=SEED_TIMEOUT)
        except Exception: raw = []

    found = []
    for item in raw:
        if item and not isinstance(item, Exception):
            if isinstance(item, list): found.extend(item)
            else: found.append(item)
            
    return (seed, found) if found else None
