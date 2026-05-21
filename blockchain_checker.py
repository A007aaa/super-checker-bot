import asyncio
import aiohttp
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins, Bip84, Bip84Coins, Bip39MnemonicValidator
)

# ── Tunables ────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 15          # seconds per individual HTTP request
SEED_TIMEOUT      = 30          # hard cap for all checks on a single seed
MAX_RETRIES       = 2           # extra attempts after the first failure
BACKOFF_BASE      = 1.5         # exponential-backoff multiplier (1.5s, 2.25s)
CONNECTOR_LIMIT   = 100         # total simultaneous TCP connections in the pool
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BlockchainChecker/2.0; "
        "+https://github.com/blockchain-checker)"
    )
}
# ────────────────────────────────────────────────────────────────────────────


def _make_connector() -> aiohttp.TCPConnector:
    """Return a shared TCPConnector with connection pooling enabled."""
    return aiohttp.TCPConnector(
        limit=CONNECTOR_LIMIT,
        ttl_dns_cache=300,
        enable_cleanup_closed=True,
    )


async def _fetch_json(session: aiohttp.ClientSession, method: str, url: str, **kwargs):
    """
    Perform a GET or POST request with retry + exponential backoff.

    Returns the parsed JSON body on success, or None on permanent failure.
    Retries up to MAX_RETRIES times on network errors or 5xx responses.
    """
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    last_exc = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            req = getattr(session, method)
            async with req(url, timeout=timeout, headers=HEADERS, **kwargs) as res:
                if res.status == 200:
                    return await res.json(content_type=None)
                if res.status < 500:
                    # 4xx – no point retrying
                    return None
                # 5xx – fall through to retry
                last_exc = Exception(f"HTTP {res.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last_exc = exc

        if attempt < MAX_RETRIES:
            await asyncio.sleep(BACKOFF_BASE ** attempt)

    return None


async def get_addresses(seed_phrase):
    """Gera endereços para múltiplas blockchains usando BIP44/BIP49/BIP84."""
    try:
        seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
        addresses = {}

        # Bitcoin (3 formatos)
        try:
            btc_bip44 = Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['BTC_Legacy'] = btc_bip44.PublicKey().ToAddress()

            btc_bip49 = Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['BTC_SegWit'] = btc_bip49.PublicKey().ToAddress()

            btc_bip84 = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['BTC_Native'] = btc_bip84.PublicKey().ToAddress()
        except:
            pass

        # Ethereum (compatível com EVM chains)
        try:
            eth = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            eth_addr = eth.PublicKey().ToAddress()
            addresses['ETH']    = eth_addr
            addresses['BSC']    = eth_addr
            addresses['AVAX']   = eth_addr
            addresses['MATIC']  = eth_addr
            addresses['ARB']    = eth_addr
            addresses['OP']     = eth_addr
            addresses['BASE']   = eth_addr
            addresses['ZKSYNC'] = eth_addr
            addresses['LINEA']  = eth_addr
        except:
            pass

        # Tron
        try:
            trx = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['TRX'] = trx.PublicKey().ToAddress()
        except:
            pass

        # Solana
        try:
            sol = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['SOL'] = sol.PublicKey().ToAddress()
        except:
            pass

        # Litecoin
        try:
            ltc = Bip44.FromSeed(seed_bytes, Bip44Coins.LITECOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['LTC'] = ltc.PublicKey().ToAddress()
        except:
            pass

        # Cardano
        try:
            ada = Bip44.FromSeed(seed_bytes, Bip44Coins.CARDANO).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['ADA'] = ada.PublicKey().ToAddress()
        except:
            pass

        # Cosmos
        try:
            atom = Bip44.FromSeed(seed_bytes, Bip44Coins.COSMOS).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['ATOM'] = atom.PublicKey().ToAddress()
        except:
            pass

        return addresses
    except:
        return {}


# ── Per-blockchain check coroutines ─────────────────────────────────────────

async def _check_btc(session: aiohttp.ClientSession, btc_type: str, addr: str):
    """Check a single Bitcoin address (any format) via blockchain.info."""
    data = await _fetch_json(session, "get",
                             f"https://blockchain.info/balance?active={addr}")
    if data is None:
        return None
    bal = data.get(addr, {}).get("final_balance", 0) / 10**8
    return (btc_type, addr, bal) if bal > 0 else None


async def _check_eth(session: aiohttp.ClientSession, eth_addr: str):
    """Check native ETH balance via BlockCypher."""
    data = await _fetch_json(session, "get",
                             f"https://api.blockcypher.com/v1/eth/main/addrs/{eth_addr}/balance")
    if data is None:
        return None
    bal = data.get("balance", 0) / 10**18
    return ("ETH", eth_addr, bal) if bal > 0 else None


async def _check_usdt_erc20(session: aiohttp.ClientSession, eth_addr: str):
    """Check USDT ERC-20 balance via Ethplorer."""
    data = await _fetch_json(session, "get",
                             f"https://api.ethplorer.io/getAddressInfo/{eth_addr}?apiKey=freekey")
    if data is None or 'tokens' not in data:
        return None
    for t in data['tokens']:
        if t['tokenInfo']['symbol'] == 'USDT':
            bal = float(t['balance']) / (10 ** int(t['tokenInfo']['decimals']))
            if bal > 0:
                return ("USDT_ERC20", eth_addr, bal)
    return None


async def _check_trx(session: aiohttp.ClientSession, trx_addr: str):
    """Check TRX native balance and USDT TRC-20 via TronGrid."""
    data = await _fetch_json(session, "get",
                             f"https://api.trongrid.io/v1/accounts/{trx_addr}")
    if data is None or not data.get('data'):
        return []

    results = []
    account = data['data'][0]

    bal = account.get('balance', 0) / 10**6
    if bal > 0:
        results.append(("TRX", trx_addr, bal))

    usdt_contract = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
    for token in account.get('trc20', []):
        if usdt_contract in token:
            usdt_bal = float(token[usdt_contract]) / 10**6
            if usdt_bal > 0:
                results.append(("USDT_TRC20", trx_addr, usdt_bal))

    return results


async def _check_sol(session: aiohttp.ClientSession, sol_addr: str):
    """Check SOL balance via Solana JSON-RPC."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [sol_addr]}
    data = await _fetch_json(session, "post",
                             "https://api.mainnet-beta.solana.com", json=payload)
    if data is None:
        return None
    bal = data.get('result', {}).get('value', 0) / 10**9
    return ("SOL", sol_addr, bal) if bal > 0 else None


# ── Main entry point ─────────────────────────────────────────────────────────

async def check_balance_all(seed):
    """
    Verifica saldos em múltiplas blockchains em paralelo.

    Todas as requisições HTTP são disparadas simultaneamente com
    asyncio.gather(), respeitando um timeout total de SEED_TIMEOUT segundos
    por seed e realizando até MAX_RETRIES tentativas por requisição.
    """
    seed = seed.strip()
    if not seed:
        return None

    try:
        if not Bip39MnemonicValidator().IsValid(seed):
            return None
    except:
        return None

    addresses = await get_addresses(seed)
    if not addresses:
        return None

    connector = _make_connector()
    async with aiohttp.ClientSession(connector=connector) as session:

        # Build the list of coroutines to run in parallel
        tasks = []

        for btc_type in ('BTC_Legacy', 'BTC_SegWit', 'BTC_Native'):
            if btc_type in addresses:
                tasks.append(_check_btc(session, btc_type, addresses[btc_type]))

        if 'ETH' in addresses:
            eth_addr = addresses['ETH']
            tasks.append(_check_eth(session, eth_addr))
            tasks.append(_check_usdt_erc20(session, eth_addr))

        if 'TRX' in addresses:
            tasks.append(_check_trx(session, addresses['TRX']))

        if 'SOL' in addresses:
            tasks.append(_check_sol(session, addresses['SOL']))

        # Run ALL blockchain checks simultaneously, bounded by SEED_TIMEOUT
        try:
            raw_results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=SEED_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raw_results = []

    # Flatten results (some checkers return a list, others a single tuple/None)
    found = []
    for item in raw_results:
        if isinstance(item, Exception) or item is None:
            continue
        if isinstance(item, list):
            found.extend(item)
        else:
            found.append(item)

    return (seed, found) if found else None
