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

# ── Hyper Turbo Tunables ────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 15          
SEED_TIMEOUT      = 180         
MAX_CONCURRENT_REQUESTS = 20    
GAP_LIMIT = 5                  
MAX_ACCOUNTS = 2                
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

RPC_URLS = {
    "BSC": ["https://bsc-dataseed.binance.org/"],
    "POLYGON": ["https://polygon-rpc.com/"],
    "ETH": ["https://cloudflare-eth.com/"],
    "ARBITRUM": ["https://arb1.arbitrum.io/rpc"],
    "OPTIMISM": ["https://mainnet.optimism.io"],
    "BASE": ["https://mainnet.base.org"]
}

USDT_CONTRACTS = {
    "ETH": "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "BSC": "0x55d398326f99059ff775485246999027b3197955",
    "POLYGON": "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"
}
# ────────────────────────────────────────────────────────────────────────────

semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def _rpc_call(session, urls, method, params):
    async with semaphore:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        random.shuffle(urls)
        for url in urls:
            try:
                async with session.post(url, json=payload, timeout=REQUEST_TIMEOUT) as res:
                    if res.status == 200:
                        data = await res.json()
                        if 'result' in data: return data
            except Exception: continue
        return None

async def get_universal_addresses(seed_phrase):
    try:
        seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
    except Exception: return []
    
    addr_map = []
    for account_idx in range(MAX_ACCOUNTS):
        for address_idx in range(GAP_LIMIT):
            # BTC (Native SegWit, SegWit, Legacy)
            try:
                addr_map.append(("BTC", "Native", Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()))
                addr_map.append(("BTC", "P2SH", Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()))
                addr_map.append(("BTC", "Legacy", Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()))
            except Exception: pass

            # LTC & DOGE
            try:
                addr_map.append(("LTC", "Native", Bip84.FromSeed(seed_bytes, Bip84Coins.LITECOIN).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()))
                addr_map.append(("DOGE", "Legacy", Bip44.FromSeed(seed_bytes, Bip44Coins.DOGECOIN).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()))
            except Exception: pass

            # EVM (ETH, BSC, Polygon, etc.)
            try:
                eth_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()
                addr_map.append(("EVM", "ADDR", eth_addr))
            except Exception: pass

            # Solana
            try:
                sol_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx)
                sol_addr = SolAddr.Encode(sol_ctx.PublicKey().Raw().ToBytes())
                addr_map.append(("SOL", "ADDR", sol_addr))
            except Exception: pass

            # Tron
            try:
                trx_addr_std = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()
                addr_map.append(("TRX", "STD", trx_addr_std))
            except Exception: pass

    return addr_map

async def check_generic_insight(session, coin, addr, api_url):
    async with semaphore:
        try:
            async with session.get(api_url.format(addr=addr), timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200:
                    data = await res.json()
                    # Diferentes APIs têm diferentes formatos de resposta
                    if "final_balance" in data: bal = data["final_balance"] / 10**8 # BTC blockchain.info
                    elif "balance" in data: bal = float(data["balance"]) / 10**8 # Blockcypher style
                    else: return None
                    if bal > 0: return (coin, addr, bal)
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
                    if bal > 0: return ("SOL", addr, bal)
        except Exception: pass
        return None

async def check_evm_full(session, addr):
    results = []
    for net, urls in RPC_URLS.items():
        data = await _rpc_call(session, urls, "eth_getBalance", [addr, "latest"])
        if data and 'result' in data:
            bal = int(data['result'], 16) / 10**18
            if bal > 0: results.append((net, addr, bal))
        
        contract = USDT_CONTRACTS.get(net)
        if contract:
            call_data = "0x70a08231" + addr[2:].zfill(64)
            t_data = await _rpc_call(session, urls, "eth_call", [{"to": contract, "data": call_data}, "latest"])
            if t_data and 'result' in t_data and t_data['result'] != '0x':
                t_bal = int(t_data['result'], 16) / 10**6
                if t_bal > 0: results.append((f"USDT_{net}", addr, t_bal))
    return results

async def check_trx(session, addr):
    async with semaphore:
        results = []
        try:
            async with session.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200:
                    data = await res.json()
                    if data.get('data') and len(data['data']) > 0:
                        acc = data['data'][0]
                        bal_trx = acc.get('balance', 0) / 10**6
                        if bal_trx > 0: results.append(("TRX", addr, bal_trx))
                        
                        trc20_list = acc.get('trc20', [])
                        for token_data in trc20_list:
                            for contract, val in token_data.items():
                                try:
                                    token_bal = float(val) / 10**6
                                    if token_bal > 0:
                                        symbol = "USDT" if contract == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' else "TRC20"
                                        results.append((symbol, addr, token_bal))
                                except: continue
        except Exception: pass
        return results

async def check_balance_all(seed):
    seed = seed.strip()
    if not seed: return None
    addr_map = await get_universal_addresses(seed)
    if not addr_map: return None

    async with aiohttp.ClientSession() as session:
        tasks = []
        for coin, label, addr in addr_map:
            if coin == "BTC": tasks.append(check_generic_insight(session, "BTC", addr, "https://blockchain.info/balance?active={addr}"))
            elif coin == "LTC": tasks.append(check_generic_insight(session, "LTC", addr, "https://api.blockcypher.com/v1/ltc/main/addrs/{addr}/balance"))
            elif coin == "DOGE": tasks.append(check_generic_insight(session, "DOGE", addr, "https://api.blockcypher.com/v1/doge/main/addrs/{addr}/balance"))
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
    
    unique_found = []
    seen_results = set()
    for coin, addr, bal in found:
        key = (coin, addr)
        if key not in seen_results:
            unique_found.append((coin, addr, bal))
            seen_results.add(key)
            
    return (seed, unique_found) if unique_found else None
