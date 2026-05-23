import asyncio
import aiohttp
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins, Bip84, Bip84Coins, Bip39MnemonicValidator
)

# ── Tunables ────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 20          
SEED_TIMEOUT      = 180         # Aumentado para o scanner universal
MAX_RETRIES       = 2           
CONNECTOR_LIMIT   = 100         
CHECK_INDEX_COUNT = 5           # Reduzido para 5 para compensar a quantidade de moedas
MAX_CONCURRENT_REQUESTS = 10    
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
# ────────────────────────────────────────────────────────────────────────────

semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def _fetch_json(session: aiohttp.ClientSession, method: str, url: str, **kwargs):
    async with semaphore:
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        for attempt in range(MAX_RETRIES + 1):
            try:
                await asyncio.sleep(0.2)
                req = getattr(session, method)
                async with req(url, timeout=timeout, headers=HEADERS, **kwargs) as res:
                    if res.status == 200: return await res.json(content_type=None)
            except: pass
            if attempt < MAX_RETRIES: await asyncio.sleep(2 ** attempt)
        return None

async def get_universal_addresses(seed_phrase):
    try:
        seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
        addr_map = []
        for i in range(CHECK_INDEX_COUNT):
            # BTC & Forks
            try:
                addr_map.append(("BTC", f"Legacy_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("BTC", f"SegWit_#{i}", Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("BTC", f"Native_#{i}", Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("LTC", f"LTC_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.LITECOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("DOGE", f"DOGE_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.DOGECOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("DASH", f"DASH_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.DASH).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("BCH", f"BCH_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN_CASH).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except: pass
            # EVM (ETH, BSC, Polygon, etc)
            try:
                eth_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()
                addr_map.append(("EVM", f"ADDR_#{i}", eth_addr))
            except: pass
            # Outras Redes
            try:
                addr_map.append(("TRX", f"TRX_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("SOL", f"SOL_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("XRP", f"XRP_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.RIPPLE).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("ADA", f"ADA_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.CARDANO).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except: pass
        return addr_map
    except: return []

async def check_balance_generic(session, coin, label, addr, api_url, divisor=10**8):
    data = await _fetch_json(session, "get", api_url)
    if data:
        # Tenta encontrar o campo de saldo em diferentes formatos de API
        bal = data.get("balance", data.get("final_balance", data.get("confirmed", 0)))
        if isinstance(bal, dict): bal = bal.get("balance", 0)
        bal = float(bal) / divisor
        if bal > 0: return (f"{coin} ({label})", addr, bal)
    return None

async def check_evm_universal(session, label, addr):
    results = []
    # ETH & BSC via BlockCypher
    for net in ["eth", "bsc"]:
        data = await _fetch_json(session, "get", f"https://api.blockcypher.com/v1/{net}/main/addrs/{addr}/balance")
        if data and data.get("balance", 0) > 0:
            results.append((f"{net.upper()} ({label})", addr, data["balance"] / 10**18))
    # Tokens via Ethplorer
    data_t = await _fetch_json(session, "get", f"https://api.ethplorer.io/getAddressInfo/{addr}?apiKey=freekey")
    if data_t and 'tokens' in data_t:
        for t in data_t['tokens']:
            bal = float(t['balance']) / (10 ** int(t['tokenInfo']['decimals']))
            if bal > 0: results.append((f"TOKEN_{t['tokenInfo']['symbol']} ({label})", addr, bal))
    return results

async def check_trx_universal(session, label, addr):
    results = []
    data = await _fetch_json(session, "get", f"https://api.trongrid.io/v1/accounts/{addr}")
    if data and data.get('data'):
        acc = data['data'][0]
        if acc.get('balance', 0) > 0: results.append((f"TRX ({label})", addr, acc['balance'] / 10**6))
        for t in acc.get('trc20', []):
            for contract, balance in t.items():
                if float(balance) > 0:
                    symbol = "USDT" if contract == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' else "TRC20_TOKEN"
                    results.append((f"{symbol} ({label})", addr, float(balance)/10**6))
    return results

async def check_sol_universal(session, label, addr):
    p = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
    data = await _fetch_json(session, "post", "https://api.mainnet-beta.solana.com", json=p)
    if data and data.get('result', {}).get('value', 0) > 0:
        return (f"SOL ({label})", addr, data['result']['value'] / 10**9)
    return None

async def check_balance_all(seed):
    seed = seed.strip()
    if not seed or not Bip39MnemonicValidator().IsValid(seed): return None
    addr_map = await get_universal_addresses(seed)
    if not addr_map: return None

    connector = aiohttp.TCPConnector(limit=CONNECTOR_LIMIT, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        for coin, label, addr in addr_map:
            if coin == "BTC": tasks.append(check_balance_generic(session, "BTC", label, addr, f"https://blockchain.info/balance?active={addr}"))
            elif coin == "LTC": tasks.append(check_balance_generic(session, "LTC", label, addr, f"https://api.blockcypher.com/v1/ltc/main/addrs/{addr}/balance"))
            elif coin == "DOGE": tasks.append(check_balance_generic(session, "DOGE", label, addr, f"https://api.blockcypher.com/v1/doge/main/addrs/{addr}/balance"))
            elif coin == "DASH": tasks.append(check_balance_generic(session, "DASH", label, addr, f"https://api.blockcypher.com/v1/dash/main/addrs/{addr}/balance"))
            elif coin == "EVM": tasks.append(check_evm_universal(session, label, addr))
            elif coin == "TRX": tasks.append(check_trx_universal(session, label, addr))
            elif coin == "SOL": tasks.append(check_sol_universal(session, label, addr))
        
        try:
            raw = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=SEED_TIMEOUT)
        except: raw = []

    found = []
    for item in raw:
        if item and not isinstance(item, Exception):
            if isinstance(item, list): found.extend(item)
            else: found.append(item)
    return (seed, found) if found else None
