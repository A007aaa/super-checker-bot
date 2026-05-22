import asyncio
import aiohttp
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins, Bip84, Bip84Coins, Bip39MnemonicValidator
)

# ── Tunables ────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 15          
SEED_TIMEOUT      = 90          # Aumentado para 10 endereços e mais redes
MAX_RETRIES       = 2           
CONNECTOR_LIMIT   = 100         
CHECK_INDEX_COUNT = 10          # Verifica os primeiros 10 endereços (Padrão Trust/MetaMask)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
# ────────────────────────────────────────────────────────────────────────────

def _make_connector() -> aiohttp.TCPConnector:
    return aiohttp.TCPConnector(limit=CONNECTOR_LIMIT, ttl_dns_cache=300, enable_cleanup_closed=True)

async def _fetch_json(session: aiohttp.ClientSession, method: str, url: str, **kwargs):
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = getattr(session, method)
            async with req(url, timeout=timeout, headers=HEADERS, **kwargs) as res:
                if res.status == 200: return await res.json(content_type=None)
        except: pass
        if attempt < MAX_RETRIES: await asyncio.sleep(1.5 ** attempt)
    return None

async def get_all_addresses(seed_phrase):
    try:
        seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
        addr_map = []
        for i in range(CHECK_INDEX_COUNT):
            # BTC (Legacy, SegWit, Native)
            try:
                addr_map.append(("BTC", f"Legacy_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("BTC", f"SegWit_#{i}", Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("BTC", f"Native_#{i}", Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except: pass
            # EVM (ETH, BSC, Polygon, AVAX, Arbitrum) - Mesmo endereço
            try:
                eth_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()
                addr_map.append(("EVM", f"ADDR_#{i}", eth_addr))
            except: pass
            # Tron
            try:
                addr_map.append(("TRX", f"TRX_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except: pass
            # Solana
            try:
                addr_map.append(("SOL", f"SOL_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except: pass
        return addr_map
    except: return []

async def check_btc(session, label, addr):
    data = await _fetch_json(session, "get", f"https://blockchain.info/balance?active={addr}")
    if data:
        bal = data.get(addr, {}).get("final_balance", 0) / 10**8
        if bal > 0: return (f"BTC ({label})", addr, bal)
    return None

async def check_evm_full(session, label, addr):
    results = []
    # 1. Ethereum (BlockCypher)
    data_eth = await _fetch_json(session, "get", f"https://api.blockcypher.com/v1/eth/main/addrs/{addr}/balance")
    if data_eth and data_eth.get("balance", 0) > 0:
        results.append((f"ETH ({label})", addr, data_eth["balance"] / 10**18))
    
    # 2. BSC (BlockCypher ou similar)
    data_bsc = await _fetch_json(session, "get", f"https://api.blockcypher.com/v1/bsc/main/addrs/{addr}/balance")
    if data_bsc and data_bsc.get("balance", 0) > 0:
        results.append((f"BNB/BSC ({label})", addr, data_bsc["balance"] / 10**18))

    # 3. Tokens ERC-20 (Ethplorer)
    data_t = await _fetch_json(session, "get", f"https://api.ethplorer.io/getAddressInfo/{addr}?apiKey=freekey")
    if data_t and 'tokens' in data_t:
        for t in data_t['tokens']:
            bal = float(t['balance']) / (10 ** int(t['tokenInfo']['decimals']))
            if bal > 0: results.append((f"TOKEN_{t['tokenInfo']['symbol']} ({label})", addr, bal))
    return results

async def check_trx_full(session, label, addr):
    results = []
    data = await _fetch_json(session, "get", f"https://api.trongrid.io/v1/accounts/{addr}")
    if data and data.get('data'):
        acc = data['data'][0]
        if acc.get('balance', 0) > 0: results.append((f"TRX ({label})", addr, acc['balance'] / 10**6))
        for t in acc.get('trc20', []):
            for contract, val in t.items():
                symbol = "USDT" if contract == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' else "TRC20_TOKEN"
                if float(val) > 0: results.append((f"{symbol} ({label})", addr, float(val)/10**6))
    return results

async def check_sol_full(session, label, addr):
    results = []
    p = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
    data = await _fetch_json(session, "post", "https://api.mainnet-beta.solana.com", json=p)
    if data and data.get('result', {}).get('value', 0) > 0:
        results.append((f"SOL ({label})", addr, data['result']['value'] / 10**9))
    return results

async def check_balance_all(seed):
    seed = seed.strip()
    if not seed or not Bip39MnemonicValidator().IsValid(seed): return None
    addr_map = await get_all_addresses(seed)
    if not addr_map: return None

    connector = _make_connector()
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        for coin, label, addr in addr_map:
            if coin == "BTC": tasks.append(check_btc(session, label, addr))
            elif coin == "EVM": tasks.append(check_evm_full(session, label, addr))
            elif coin == "TRX": tasks.append(check_trx_full(session, label, addr))
            elif coin == "SOL": tasks.append(check_sol_full(session, label, addr))
        
        try:
            raw = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=SEED_TIMEOUT)
        except: raw = []

    found = []
    for item in raw:
        if item and not isinstance(item, Exception):
            if isinstance(item, list): found.extend(item)
            else: found.append(item)
    return (seed, found) if found else None
