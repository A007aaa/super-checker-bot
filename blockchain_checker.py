import asyncio
import aiohttp
import logging
import os
import random
import json
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip84, Bip84Coins
)

logger = logging.getLogger(__name__)

# Configuráveis via ENV (sensible defaults embedded)
CHECK_CONCURRENCY = int(os.getenv('CHECK_CONCURRENCY', '80'))  # global concurrent network calls
PER_PROVIDER_LIMIT = int(os.getenv('PER_PROVIDER_LIMIT', '20'))
SCAN_ADDRESSES = int(os.getenv('SCAN_ADDRESSES', '20'))        # default per-account indexes
SCAN_ACCOUNTS = int(os.getenv('SCAN_ACCOUNTS', '1'))           # default account indices
CHECK_TIMEOUT = int(os.getenv('CHECK_TIMEOUT', '30'))         # seconds per HTTP request
CHECK_RETRIES = int(os.getenv('CHECK_RETRIES', '2'))
RETRY_BACKOFF_BASE = float(os.getenv('RETRY_BACKOFF_BASE', '1.5'))

# Provider endpoints (can be overridden by env or extended)
PROVIDERS = {
    'eth': [os.getenv('ETH_RPC', 'https://cloudflare-eth.com/')],
    'sol': [os.getenv('SOL_RPC', 'https://api.mainnet-beta.solana.com')],
    'btc': [os.getenv('BTC_API', 'https://blockchain.info/q/addressbalance/')],
    'tron': [os.getenv('TRON_API', 'https://api.trongrid.io/v1/accounts/')]
}

# Concurrency controls
GLOBAL_SEMAPHORE = asyncio.Semaphore(CHECK_CONCURRENCY)
PROVIDER_SEMAPHORES = {k: asyncio.Semaphore(PER_PROVIDER_LIMIT) for k in PROVIDERS}

# module-level session reused to reduce connection overhead
_global_session = None


def _ensure_session():
    global _global_session
    if _global_session is None or getattr(_global_session, 'closed', False):
        _global_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=CHECK_CONCURRENCY))
    return _global_session


async def _fetch_with_retries(session, method: str, url: str, provider: str = None, **kwargs):
    """Perform HTTP request with retries and exponential backoff.

    Returns a tuple (status:int, text:str). Do NOT return the response object because the
    aiohttp response is closed when exiting the request context manager.
    """
    last_exc = None
    for attempt in range(1, CHECK_RETRIES + 2):
        try:
            timeout = aiohttp.ClientTimeout(total=CHECK_TIMEOUT)
            async with session.request(method, url, timeout=timeout, **kwargs) as res:
                try:
                    text = await res.text()
                except Exception:
                    text = None
                logger.debug(f"HTTP {method} {url} [attempt {attempt}] -> status {res.status}")
                return res.status, text
        except asyncio.TimeoutError as e:
            logger.warning(f"   ⏱️ Timeout {method} {url} attempt {attempt}/{CHECK_RETRIES+1}")
            last_exc = e
        except aiohttp.ClientError as e:
            logger.warning(f"   ⚠️ HTTP client error on {method} {url} attempt {attempt}: {e}")
            last_exc = e
        except Exception as e:
            logger.error(f"   ❌ Unexpected error on {method} {url} attempt {attempt}: {e}")
            last_exc = e

        # backoff
        if attempt <= CHECK_RETRIES + 1:
            backoff = (RETRY_BACKOFF_BASE ** (attempt - 1)) * (0.5 + random.random() * 0.5)
            await asyncio.sleep(backoff)

    raise last_exc


# Low-level checks (kept similar, but now use status/text instead of response objects)
async def check_sol(session, addr):
    async with PROVIDER_SEMAPHORES['sol']:
        try:
            logger.debug(f"   🌐 [SOL] Verificando endereço: {addr}")
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
            status, text = await _fetch_with_retries(session, 'POST', PROVIDERS['sol'][0], provider='sol', json=payload)
            if status == 200:
                try:
                    data = json.loads(text) if text else {}
                except Exception:
                    data = {}
                bal = data.get('result', {}).get('value', 0) / 10**9
                if bal > 0:
                    logger.info(f"   💰 [SOL] Saldo encontrado: {bal} SOL em {addr}")
                    return (('SOL', addr, bal),)
                else:
                    logger.debug(f"   ⚪ [SOL] Saldo zero em {addr}")
            else:
                logger.debug(f"   ⚠️ [SOL] Response {status} for {addr} - body: {text}")
        except Exception as e:
            logger.error(f"   ❌ [SOL] Erro ao verificar {addr}: {e}")
    return ()


async def check_eth_usdt(session, addr):
    async with PROVIDER_SEMAPHORES['eth']:
        results = []
        try:
            logger.debug(f"   🌐 [ETH] Verificando endereco: {addr}")
            payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [addr, "latest"]}
            status, text = await _fetch_with_retries(session, 'POST', PROVIDERS['eth'][0], provider='eth', json=payload)
            if status == 200:
                try:
                    data = json.loads(text) if text else {}
                except Exception:
                    data = {}
                bal = int(data.get('result', '0x0'), 16) / 10**18
                if bal > 0:
                    logger.info(f"   💰 [ETH] Saldo encontrado: {bal} ETH em {addr}")
                    results.append(("ETH", addr, bal))
                else:
                    logger.debug(f"   ⚪ [ETH] Saldo zero em {addr}")
            else:
                logger.debug(f"   ⚠️ [ETH] Response {status} for {addr} - body: {text}")

            # USDT (ERC20)
            logger.debug(f"   🌐 [USDT_ETH] Verificando endereco: {addr}")
            usdt_contract = "0xdac17f958d2ee523a2206206994597c13d831ec7"
            data_call = "0x70a08231" + addr[2:].lower().zfill(64)
            payload_u = {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": usdt_contract, "data": data_call}, "latest"]}
            status_u, text_u = await _fetch_with_retries(session, 'POST', PROVIDERS['eth'][0], provider='eth', json=payload_u)
            if status_u == 200:
                try:
                    data = json.loads(text_u) if text_u else {}
                except Exception:
                    data = {}
                u_bal = int(data.get('result', '0x0'), 16) / 10**6
                if u_bal > 0:
                    logger.info(f"   💰 [USDT_ETH] Saldo encontrado: {u_bal} USDT em {addr}")
                    results.append(("USDT_ETH", addr, u_bal))
                else:
                    logger.debug(f"   ⚪ [USDT_ETH] Saldo zero em {addr}")
            else:
                logger.debug(f"   ⚠️ [USDT_ETH] Response {status_u} for {addr} - body: {text_u}")

        except Exception as e:
            logger.error(f"   ❌ [ETH/USDT] Erro ao verificar {addr}: {e}")
        return tuple(results)


async def check_btc(session, addr):
    async with PROVIDER_SEMAPHORES['btc']:
        try:
            logger.debug(f"   🌐 [BTC] Verificando endereco: {addr}")
            status, text = await _fetch_with_retries(session, 'GET', PROVIDERS['btc'][0] + addr, provider='btc')
            if status == 200:
                try:
                    bal = int(text) / 10**8
                except Exception:
                    bal = 0
                if bal > 0:
                    logger.info(f"   💰 [BTC] Saldo encontrado: {bal} BTC em {addr}")
                    return (('BTC', addr, bal),)
                else:
                    logger.debug(f"   ⚪ [BTC] Saldo zero em {addr}")
            else:
                logger.debug(f"   ⚠️ [BTC] Response {status} for {addr} - body: {text}")
        except Exception as e:
            logger.error(f"   ❌ [BTC] Erro ao verificar {addr}: {e}")
    return ()


async def check_tron_usdt(session, addr):
    async with PROVIDER_SEMAPHORES['tron']:
        results = []
        try:
            logger.debug(f"   🌐 [TRX] Verificando endereco: {addr}")
            status, text = await _fetch_with_retries(session, 'GET', PROVIDERS['tron'][0] + addr, provider='tron')
            if status == 200:
                try:
                    data = json.loads(text) if text else {}
                except Exception:
                    data = {}
                if data.get('data'):
                    acc = data['data'][0]
                    trx_bal = acc.get('balance', 0) / 10**6
                    if trx_bal > 0:
                        logger.info(f"   💰 [TRX] Saldo encontrado: {trx_bal} TRX em {addr}")
                        results.append(("TRX", addr, trx_bal))
                    else:
                        logger.debug(f"   ⚪ [TRX] Saldo zero em {addr}")
                    trc20_list = acc.get('trc20', [])
                    for token in trc20_list:
                        try:
                            if isinstance(token, dict):
                                if 'balance' in token and 'tokenId' in token and token.get('tokenId') == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t':
                                    u_bal = float(token['balance']) / 10**6
                                else:
                                    for k, v in token.items():
                                        if 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' in str(k):
                                            u_bal = float(v) / 10**6
                                            break
                                    else:
                                        continue
                            else:
                                continue
                        except Exception:
                            continue

                        if u_bal > 0:
                            logger.info(f"   💰 [USDT_TRX] Saldo encontrado: {u_bal} USDT em {addr}")
                            results.append(("USDT_TRX", addr, u_bal))
                        else:
                            logger.debug(f"   ⚪ [USDT_TRX] Saldo zero em {addr}")
                else:
                    logger.debug(f"   ⚪ [TRX] Conta nao encontrada / sem dados em {addr}")
            else:
                logger.debug(f"   ⚠️ [TRX] Response {status} for {addr} - body: {text}")
        except Exception as e:
            logger.error(f"   ❌ [TRX] Erro ao verificar {addr}: {e}")
        return tuple(results)


# New streaming check function used by bulk_processor. It avoids building big maps and can early-stop.
async def check_seed_params(session, seed: str, accounts: int = 1, indexes: int = 5, early_stop: bool = True):
    """
    Stream-derived address checks for a seed. Returns (seed, found_list) or None.
    This function is intentionally conservative: it checks addresses one-by-one under provider semaphores to avoid spikes.
    bulk_processor should run many seeds concurrently to keep throughput.
    """
    found = []
    try:
        # derivation is CPU-bound; run in thread to avoid blocking event loop
        seed_bytes = await asyncio.to_thread(lambda: Bip39SeedGenerator(seed).Generate())
    except Exception as e:
        logger.error(f"   ❌ Erro na derivacao da seed: {e}")
        return None

    # Iterate and check sequentially per seed (keeps memory low). Bulk parallelism handled by bulk_processor.
    for acct in range(max(1, accounts)):
        for idx in range(max(1, indexes)):
            try:
                # derive addresses in thread to avoid blocking
                def derive_index(sb, a, i):
                    b84 = Bip84.FromSeed(sb, Bip84Coins.BITCOIN).Purpose().Coin().Account(a).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i)
                    btc_sgw = b84.PublicKey().ToAddress()
                    b44_btc = Bip44.FromSeed(sb, Bip44Coins.BITCOIN).Purpose().Coin().Account(a).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i)
                    btc_leg = b44_btc.PublicKey().ToAddress()
                    eth = Bip44.FromSeed(sb, Bip44Coins.ETHEREUM).Purpose().Coin().Account(a).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i)
                    eth_addr = eth.PublicKey().ToAddress()
                    sol = Bip44.FromSeed(sb, Bip44Coins.SOLANA).Purpose().Coin().Account(a).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i)
                    sol_addr = sol.PublicKey().ToAddress()
                    trx = Bip44.FromSeed(sb, Bip44Coins.TRON).Purpose().Coin().Account(a).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i)
                    trx_addr = trx.PublicKey().ToAddress()
                    return btc_sgw, btc_leg, eth_addr, sol_addr, trx_addr

                btc_sgw, btc_leg, eth_addr, sol_addr, trx_addr = await asyncio.to_thread(derive_index, seed_bytes, acct, idx)

                # run provider checks in parallel per-index (they each use provider semaphores internally)
                tasks = [
                    asyncio.create_task(check_eth_usdt(session, eth_addr)),
                    asyncio.create_task(check_btc(session, btc_sgw)),
                    asyncio.create_task(check_btc(session, btc_leg)),
                    asyncio.create_task(check_sol(session, sol_addr)),
                    asyncio.create_task(check_tron_usdt(session, trx_addr)),
                ]

                results = await asyncio.gather(*tasks, return_exceptions=True)
                for res in results:
                    if isinstance(res, Exception):
                        logger.debug(f"   ⚠️ Provider check exception: {res}")
                        continue
                    if res:
                        # res can be tuple of results
                        if isinstance(res, tuple):
                            found.extend(res)
                        else:
                            found.append(res)

                if found and early_stop:
                    logger.info(f"   ✅ Encontrado saldo em seed (acct={acct} idx={idx}) - interrompendo early_stop")
                    return (seed, found)

            except Exception as e:
                logger.debug(f"   ⚠️ Falha ao derivar/verificar acct={acct} idx={idx}: {e}")
                continue

    if found:
        return (seed, found)
    return None


# Backwards-compatible check_balance_master (keeps previous behaviour but uses streaming under the hood)
async def check_balance_master(type, value):
    logger.info(f"🔍 Iniciando verificação: tipo={type}")
    # reuse a global session to reduce connection overhead
    session = _ensure_session()
    if type == 'SEED':
        # use defaults from env/config
        return await check_seed_params(session, value, SCAN_ACCOUNTS, SCAN_ADDRESSES, early_stop=True)

    # other types (keys/addresses) keep original behaviour
    if type == "KEY_SOL":
        return await check_sol(session, value)
    if type == "KEY_HEX":
        addr = value if value.startswith("0x") else f"0x{value}"
        return await check_eth_usdt(session, addr)
    if type == "ADDR_ETH":
        return await check_eth_usdt(session, value)
    if type == "ADDR_BTC":
        return await check_btc(session, value)
    if type == "ADDR_TRON":
        return await check_tron_usdt(session, value)
    if type == "ADDR_SOL":
        return await check_sol(session, value)

    # fallback: detect by prefix
    if isinstance(value, str):
        if value.startswith("0x") and len(value) == 42:
            return await check_eth_usdt(session, value)
        elif value.startswith("T") and len(value) == 34:
            return await check_tron_usdt(session, value)
        elif value.startswith("bc1") or value.startswith(("1", "3")):
            return await check_btc(session, value)
    return await check_sol(session, value)
