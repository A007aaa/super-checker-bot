import asyncio
import aiohttp
import json
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins, Bip84, Bip84Coins, Bip39MnemonicValidator
)

# ── Super Turbo Tunables ────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 8           # Timeouts curtos para não travar
SEED_TIMEOUT      = 45          
MAX_CONCURRENT_REQUESTS = 30    # Alta concorrência
CHECK_INDEX_COUNT = 2           # Foco nos 2 primeiros endereços (95% dos casos)
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

# Múltiplos RPCs para evitar bloqueios
RPC_URLS = {
    "BSC": ["https://bsc-dataseed.binance.org/", "https://bsc-dataseed1.defibit.io/"],
    "POLYGON": ["https://polygon-rpc.com/", "https://rpc-mainnet.maticvigil.com/"],
    "ETH": ["https://cloudflare-eth.com/", "https://eth-mainnet.public.blastapi.io"]
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
        for url in urls:
            try:
                async with session.post(url, json=payload, timeout=REQUEST_TIMEOUT) as res:
                    if res.status == 200:
                        data = await res.json()
                        if 'result' in data: return data
            except: continue
        return None

async def get_universal_addresses(seed_phrase):
    try:
        seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
        addr_map = []
        for i in range(CHECK_INDEX_COUNT):
            # BTC (SegWit & Native)
            try:
                addr_map.append(("BTC", f"SegWit_#{i}", Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("BTC", f"Native_#{i}", Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except: pass
            # EVM
            try:
                eth_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()
                addr_map.append(("EVM", f"ADDR_#{i}", eth_addr))
            except: pass
            # Tron
            try:
                addr_map.append(("TRX", f"TRX_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except: pass
        return addr_map
    except: return []

async def check_btc(session, label, addr):
    async with semaphore:
        try:
            async with session.get(f"https://blockchain.info/balance?active={addr}", timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200:
                    data = await res.json()
                    bal = data.get(addr, {}).get("final_balance", 0) / 10**8
                    if bal > 0: return (f"BTC ({label})", addr, bal)
        except: pass
        return None

async def check_evm_full(session, label, addr):
    results = []
    for net, urls in RPC_URLS.items():
        data = await _rpc_call(session, urls, "eth_getBalance", [addr, "latest"])
        if data and 'result' in data:
            bal = int(data['result'], 16) / 10**18
            if bal > 0.0001: results.append((f"{net} ({label})", addr, bal))
        
        contract = USDT_CONTRACTS.get(net)
        if contract:
            call_data = "0x70a08231" + addr[2:].zfill(64)
            t_data = await _rpc_call(session, urls, "eth_call", [{"to": contract, "data": call_data}, "latest"])
            if t_data and 'result' in t_data and t_data['result'] != '0x':
                t_bal = int(t_data['result'], 16) / 10**6
                if t_bal > 0.1: results.append((f"USDT_{net} ({label})", addr, t_bal))
    return results

async def check_trx(session, label, addr):
    async with semaphore:
        try:
            async with session.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200:
                    data = await res.json()
                    if data.get('data'):
                        acc = data['data'][0]
                        bal = acc.get('balance', 0) / 10**6
                        if bal > 0: return [(f"TRX ({label})", addr, bal)]
                        for t in acc.get('trc20', []):
                            for contract, val in t.items():
                                if float(val) > 0:
                                    symbol = "USDT" if contract == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' else "TRC20"
                                    return [(f"{symbol} ({label})", addr, float(val)/10**6)]
        except: pass
        return []

async def check_balance_all(seed):
    seed = seed.strip()
    if not seed or not Bip39MnemonicValidator().IsValid(seed): return None
    addr_map = await get_universal_addresses(seed)
    if not addr_map: return None

    async with aiohttp.ClientSession() as session:
        tasks = []
        for coin, label, addr in addr_map:
            if coin == "BTC": tasks.append(check_btc(session, label, addr))
            elif coin == "EVM": tasks.append(check_evm_full(session, label, addr))
            elif coin == "TRX": tasks.append(check_trx(session, label, addr))
        
        try:
            raw = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=SEED_TIMEOUT)
        except: raw = []

    found = []
    for item in raw:
        if item and not isinstance(item, Exception):
            if isinstance(item, list): found.extend(item)
            else: found.append(item)
    return (seed, found) if found else None
