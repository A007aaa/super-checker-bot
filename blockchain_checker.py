import asyncio
import aiohttp
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins, Bip84, Bip84Coins, Bip39MnemonicValidator
)

# ── Tunables ────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 15          
SEED_TIMEOUT      = 45          # Aumentado para suportar mais redes
MAX_RETRIES       = 2           
BACKOFF_BASE      = 1.5         
CONNECTOR_LIMIT   = 100         
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BlockchainChecker/3.0; +https://github.com/blockchain-checker)"
}
# ────────────────────────────────────────────────────────────────────────────

def _make_connector() -> aiohttp.TCPConnector:
    return aiohttp.TCPConnector(limit=CONNECTOR_LIMIT, ttl_dns_cache=300, enable_cleanup_closed=True)

async def _fetch_json(session: aiohttp.ClientSession, method: str, url: str, **kwargs):
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = getattr(session, method)
            async with req(url, timeout=timeout, headers=HEADERS, **kwargs) as res:
                if res.status == 200:
                    return await res.json(content_type=None)
                if res.status < 500: return None
        except: pass
        if attempt < MAX_RETRIES: await asyncio.sleep(BACKOFF_BASE ** attempt)
    return None

async def get_addresses(seed_phrase):
    try:
        seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
        addresses = {}
        # Bitcoin
        try:
            addresses['BTC_Legacy'] = Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
            addresses['BTC_SegWit'] = Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
            addresses['BTC_Native'] = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
        except: pass
        # EVM
        try:
            eth_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
            addresses['ETH'] = eth_addr
        except: pass
        # Tron
        try:
            addresses['TRX'] = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
        except: pass
        # Solana
        try:
            addresses['SOL'] = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
        except: pass
        # Outras
        try:
            addresses['LTC'] = Bip44.FromSeed(seed_bytes, Bip44Coins.LITECOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
            addresses['ADA'] = Bip44.FromSeed(seed_bytes, Bip44Coins.CARDANO).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
            addresses['ATOM'] = Bip44.FromSeed(seed_bytes, Bip44Coins.COSMOS).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
        except: pass
        return addresses
    except: return {}

async def _check_btc(session, btc_type, addr):
    data = await _fetch_json(session, "get", f"https://blockchain.info/balance?active={addr}")
    if data:
        bal = data.get(addr, {}).get("final_balance", 0) / 10**8
        if bal > 0: return (btc_type, addr, bal)
    return None

async def _check_eth_tokens(session, eth_addr):
    results = []
    # Native ETH
    data_eth = await _fetch_json(session, "get", f"https://api.blockcypher.com/v1/eth/main/addrs/{eth_addr}/balance")
    if data_eth:
        bal = data_eth.get("balance", 0) / 10**18
        if bal > 0: results.append(("ETH", eth_addr, bal))
    # ERC-20 Tokens
    data_tokens = await _fetch_json(session, "get", f"https://api.ethplorer.io/getAddressInfo/{eth_addr}?apiKey=freekey")
    if data_tokens and 'tokens' in data_tokens:
        for t in data_tokens['tokens']:
            symbol = t['tokenInfo']['symbol']
            bal = float(t['balance']) / (10 ** int(t['tokenInfo']['decimals']))
            if bal > 0: results.append((f"TOKEN_{symbol}", eth_addr, bal))
    return results

async def _check_trx_tokens(session, trx_addr):
    results = []
    data = await _fetch_json(session, "get", f"https://api.trongrid.io/v1/accounts/{trx_addr}")
    if data and data.get('data'):
        account = data['data'][0]
        # Native TRX
        bal = account.get('balance', 0) / 10**6
        if bal > 0: results.append(("TRX", trx_addr, bal))
        # TRC-20 Tokens
        for token in account.get('trc20', []):
            for contract, balance in token.items():
                # Nota: TronGrid não retorna o símbolo do token aqui, apenas o contrato. 
                # Simplificando para mostrar que há saldo.
                bal_token = float(balance) / 10**6 # Assumindo 6 decimais (comum em USDT)
                if bal_token > 0: results.append((f"TRC20_TOKEN", trx_addr, bal_token))
    return results

async def _check_sol_tokens(session, sol_addr):
    results = []
    # Native SOL
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [sol_addr]}
    data = await _fetch_json(session, "post", "https://api.mainnet-beta.solana.com", json=payload)
    if data:
        bal = data.get('result', {}).get('value', 0) / 10**9
        if bal > 0: results.append(("SOL", sol_addr, bal))
    # SPL Tokens
    payload_tokens = {"jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner", "params": [sol_addr, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding": "jsonParsed"}]}
    data_tokens = await _fetch_json(session, "post", "https://api.mainnet-beta.solana.com", json=payload_tokens)
    if data_tokens and 'result' in data_tokens:
        for account in data_tokens['result']['value']:
            info = account['account']['data']['parsed']['info']
            bal = float(info['tokenAmount']['uiAmount'])
            if bal > 0: results.append((f"SPL_TOKEN", sol_addr, bal))
    return results

async def _check_generic(session, coin_name, addr, api_url, decimal_factor):
    data = await _fetch_json(session, "get", api_url)
    if data:
        bal = data.get("balance", 0) / 10**decimal_factor
        if bal > 0: return (coin_name, addr, bal)
    return None

async def check_balance_all(seed):
    seed = seed.strip()
    if not seed or not Bip39MnemonicValidator().IsValid(seed): return None
    addresses = await get_addresses(seed)
    if not addresses: return None

    connector = _make_connector()
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        for btc in ('BTC_Legacy', 'BTC_SegWit', 'BTC_Native'):
            if btc in addresses: tasks.append(_check_btc(session, btc, addresses[btc]))
        if 'ETH' in addresses: tasks.append(_check_eth_tokens(session, addresses['ETH']))
        if 'TRX' in addresses: tasks.append(_check_trx_tokens(session, addresses['TRX']))
        if 'SOL' in addresses: tasks.append(_check_sol_tokens(session, addresses['SOL']))
        if 'LTC' in addresses: tasks.append(_check_generic(session, "LTC", addresses['LTC'], f"https://api.blockcypher.com/v1/ltc/main/addrs/{addresses['LTC']}/balance", 8))
        if 'ADA' in addresses: tasks.append(_check_generic(session, "ADA", addresses['ADA'], f"https://api.blockcypher.com/v1/ada/main/addrs/{addresses['ADA']}/balance", 6))
        
        try:
            raw_results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=SEED_TIMEOUT)
        except: raw_results = []

    found = []
    for item in raw_results:
        if item and not isinstance(item, Exception):
            if isinstance(item, list): found.extend(item)
            else: found.append(item)
    return (seed, found) if found else None
