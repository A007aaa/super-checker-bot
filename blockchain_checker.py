import asyncio
import aiohttp
import json
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins, Bip84, Bip84Coins, Bip39MnemonicValidator
)

# ── Tunables ────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 20          
SEED_TIMEOUT      = 180         
MAX_RETRIES       = 2           
CHECK_INDEX_COUNT = 5           
MAX_CONCURRENT_REQUESTS = 5     
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

# RPCs Públicos (Mais confiáveis que APIs de terceiros)
RPC_URLS = {
    "BSC": "https://bsc-dataseed.binance.org/",
    "POLYGON": "https://polygon-rpc.com/",
    "ETH": "https://cloudflare-eth.com/",
    "SOL": "https://api.mainnet-beta.solana.com"
}
# ────────────────────────────────────────────────────────────────────────────

semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def _rpc_call(session, url, method, params):
    async with semaphore:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            async with session.post(url, json=payload, timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200: return await res.json()
        except: pass
        return None

async def get_universal_addresses(seed_phrase):
    try:
        seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
        addr_map = []
        for i in range(CHECK_INDEX_COUNT):
            # BTC
            try:
                addr_map.append(("BTC", f"Legacy_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
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
    try:
        async with session.get(f"https://blockchain.info/balance?active={addr}", timeout=REQUEST_TIMEOUT) as res:
            if res.status == 200:
                data = await res.json()
                bal = data.get(addr, {}).get("final_balance", 0) / 10**8
                if bal > 0: return (f"BTC ({label})", addr, bal)
    except: pass
    return None

async def check_evm_rpc(session, network, label, addr):
    url = RPC_URLS.get(network)
    if not url: return None
    data = await _rpc_call(session, url, "eth_getBalance", [addr, "latest"])
    if data and 'result' in data:
        bal = int(data['result'], 16) / 10**18
        if bal > 0: return (f"{network} ({label})", addr, bal)
    return None

async def check_trx(session, label, addr):
    try:
        async with session.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=REQUEST_TIMEOUT) as res:
            if res.status == 200:
                data = await res.json()
                if data.get('data'):
                    acc = data['data'][0]
                    bal = acc.get('balance', 0) / 10**6
                    if bal > 0: return (f"TRX ({label})", addr, bal)
                    # Check USDT
                    for t in acc.get('trc20', []):
                        for contract, val in t.items():
                            if contract == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' and float(val) > 0:
                                return (f"USDT_TRC20 ({label})", addr, float(val)/10**6)
    except: pass
    return None

async def check_balance_all(seed):
    seed = seed.strip()
    if not seed or not Bip39MnemonicValidator().IsValid(seed): return None
    addr_map = await get_universal_addresses(seed)
    if not addr_map: return None

    async with aiohttp.ClientSession() as session:
        tasks = []
        for coin, label, addr in addr_map:
            if coin == "BTC": tasks.append(check_btc(session, label, addr))
            elif coin == "EVM":
                tasks.append(check_evm_rpc(session, "ETH", label, addr))
                tasks.append(check_evm_rpc(session, "BSC", label, addr))
                tasks.append(check_evm_rpc(session, "POLYGON", label, addr))
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
