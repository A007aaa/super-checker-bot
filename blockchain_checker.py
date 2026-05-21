import asyncio
import aiohttp
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins, Bip84, Bip84Coins, Bip39MnemonicValidator
)

# ── Tunables ────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 15          
SEED_TIMEOUT      = 60          # Aumentado para suportar múltiplos endereços
MAX_RETRIES       = 2           
CONNECTOR_LIMIT   = 100         
CHECK_INDEX_COUNT = 5           # Verifica os primeiros 5 endereços (0 a 4)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BlockchainChecker/4.0)"}
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
    """Gera endereços para os primeiros N índices de cada moeda."""
    try:
        seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
        addr_map = [] # Lista de (moeda, tipo, endereco)

        for i in range(CHECK_INDEX_COUNT):
            # Bitcoin
            try:
                addr_map.append(("BTC", f"Legacy_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("BTC", f"SegWit_#{i}", Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("BTC", f"Native_#{i}", Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except: pass
            # ETH / EVM
            try:
                addr_map.append(("ETH", f"ETH_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except: pass
            # Tron
            try:
                addr_map.append(("TRX", f"TRX_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except: pass
            # Solana
            try:
                addr_map.append(("SOL", f"SOL_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except: pass
            # Litecoin
            try:
                addr_map.append(("LTC", f"LTC_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.LITECOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except: pass

        return addr_map
    except: return []

async def check_btc(session, coin, label, addr):
    data = await _fetch_json(session, "get", f"https://blockchain.info/balance?active={addr}")
    if data:
        bal = data.get(addr, {}).get("final_balance", 0) / 10**8
        if bal > 0: return (f"{coin} ({label})", addr, bal)
    return None

async def check_eth_full(session, label, addr):
    results = []
    # Native
    data = await _fetch_json(session, "get", f"https://api.blockcypher.com/v1/eth/main/addrs/{addr}/balance")
    if data and data.get("balance", 0) > 0:
        results.append((f"ETH ({label})", addr, data["balance"] / 10**18))
    # Tokens
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
            for _, val in t.items():
                if float(val) > 0: results.append((f"TRC20_TOKEN ({label})", addr, float(val)/10**6))
    return results

async def check_sol_full(session, label, addr):
    results = []
    # Native
    p = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
    data = await _fetch_json(session, "post", "https://api.mainnet-beta.solana.com", json=p)
    if data and data.get('result', {}).get('value', 0) > 0:
        results.append((f"SOL ({label})", addr, data['result']['value'] / 10**9))
    return results

async def check_ltc(session, label, addr):
    data = await _fetch_json(session, "get", f"https://api.blockcypher.com/v1/ltc/main/addrs/{addr}/balance")
    if data and data.get("balance", 0) > 0:
        return (f"LTC ({label})", addr, data["balance"] / 10**8)
    return None

async def check_balance_all(seed):
    seed = seed.strip()
    if not seed or not Bip39MnemonicValidator().IsValid(seed): return None
    addr_map = await get_all_addresses(seed)
    if not addr_map: return None

    connector = _make_connector()
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        for coin, label, addr in addr_map:
            if coin == "BTC": tasks.append(check_btc(session, coin, label, addr))
            elif coin == "ETH": tasks.append(check_eth_full(session, label, addr))
            elif coin == "TRX": tasks.append(check_trx_full(session, label, addr))
            elif coin == "SOL": tasks.append(check_sol_full(session, label, addr))
            elif coin == "LTC": tasks.append(check_ltc(session, label, addr))
        
        try:
            raw = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=SEED_TIMEOUT)
        except: raw = []

    found = []
    for item in raw:
        if item and not isinstance(item, Exception):
            if isinstance(item, list): found.extend(item)
            else: found.append(item)
    return (seed, found) if found else None
