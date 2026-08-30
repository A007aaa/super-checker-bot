import asyncio
import aiohttp
import logging
import os
import random
import json
from bip_utils import (
    Bip39SeedGenerator,
    Bip44,
    Bip44Coins,
    Bip44Changes,
    Bip84,
    Bip84Coins,
)

logger = logging.getLogger(__name__)

CHECK_CONCURRENCY = int(os.getenv("CHECK_CONCURRENCY", "80"))
PER_PROVIDER_LIMIT = int(os.getenv("PER_PROVIDER_LIMIT", "20"))
SCAN_ADDRESSES = int(os.getenv("SCAN_ADDRESSES", "20"))
SCAN_ACCOUNTS = int(os.getenv("SCAN_ACCOUNTS", "2"))
CHECK_TIMEOUT = int(os.getenv("CHECK_TIMEOUT", "15"))
CHECK_RETRIES = int(os.getenv("CHECK_RETRIES", "2"))
RETRY_BACKOFF_BASE = float(os.getenv("RETRY_BACKOFF_BASE", "1.3"))
EARLY_STOP = os.getenv("EARLY_STOP", "true").lower() in ("1", "true", "yes")

TRC20_KNOWN = {
    "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t": ("USDT_TRX", 6),
    "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8": ("USDC_TRX", 6),
}

EVM_NATIVE = {
    "ETH": (os.getenv("ETH_RPC", "https://cloudflare-eth.com/"), 18, "ETH"),
    "BNB": (os.getenv("BSC_RPC", "https://bsc-dataseed.binance.org/"), 18, "BNB"),
    "MATIC": (os.getenv("POLYGON_RPC", "https://polygon-rpc.com/"), 18, "MATIC"),
}

USDT_CONTRACTS = {
    "USDT_ETH": (os.getenv("ETH_RPC", "https://cloudflare-eth.com/"), "0xdac17f958d2ee523a2206206994597c13d831ec7", 6),
    "USDT_BSC": (os.getenv("BSC_RPC", "https://bsc-dataseed.binance.org/"), "0x55d398326f99059fF775485246999027B3197955", 18),
    "USDT_POLYGON": (os.getenv("POLYGON_RPC", "https://polygon-rpc.com/"), "0xc2132D05D31c914a87C6611C10748AEb04B58e8F", 6),
}

PROVIDERS = {
    "eth": [EVM_NATIVE["ETH"][0]],
    "bsc": [EVM_NATIVE["BNB"][0]],
    "polygon": [EVM_NATIVE["MATIC"][0]],
    "sol": [os.getenv("SOL_RPC", "https://api.mainnet-beta.solana.com")],
    "btc": [os.getenv("BTC_API", "https://blockchain.info/q/addressbalance/")],
    "tron": [os.getenv("TRON_API", "https://api.trongrid.io/v1/accounts/")],
}
PROVIDER_SEMAPHORES = {k: asyncio.Semaphore(PER_PROVIDER_LIMIT) for k in PROVIDERS}
TRON_API_KEY = os.getenv("TRON_API_KEY", "").strip()


def preview_addresses(seed: str) -> dict:
    seed_bytes = Bip39SeedGenerator(seed).Generate()
    return _derive_addrs(seed_bytes, 0, 0, Bip44Changes.CHAIN_EXT)


async def _fetch_with_retries(session, method: str, url: str, **kwargs):
    last_exc = None
    headers = dict(kwargs.pop("headers", {}) or {})
    if TRON_API_KEY and "trongrid" in url:
        headers["TRON-PRO-API-KEY"] = TRON_API_KEY
    for attempt in range(1, CHECK_RETRIES + 2):
        try:
            timeout = aiohttp.ClientTimeout(total=CHECK_TIMEOUT)
            async with session.request(
                method, url, timeout=timeout, headers=headers or None, **kwargs
            ) as res:
                try:
                    text = await res.text()
                except Exception:
                    text = None
                return res.status, text
        except Exception as e:
            last_exc = e
            if attempt <= CHECK_RETRIES + 1:
                await asyncio.sleep((RETRY_BACKOFF_BASE ** (attempt - 1)) * (0.3 + random.random() * 0.4))
    if last_exc:
        raise last_exc
    return 0, None


async def check_sol(session, addr):
    async with PROVIDER_SEMAPHORES["sol"]:
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
            status, text = await _fetch_with_retries(session, "POST", PROVIDERS["sol"][0], json=payload)
            if status == 200 and text:
                bal = json.loads(text).get("result", {}).get("value", 0) / 10**9
                if bal and bal > 0:
                    return ("SOL", addr, bal)
        except Exception as e:
            logger.debug(f"[SOL] {e}")
    return None


async def check_evm_native(session, addr, chain_key: str):
    rpc, decimals, label = EVM_NATIVE[chain_key]
    sem_key = "eth" if chain_key == "ETH" else ("bsc" if chain_key == "BNB" else "polygon")
    async with PROVIDER_SEMAPHORES[sem_key]:
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [addr, "latest"]}
            status, text = await _fetch_with_retries(session, "POST", rpc, json=payload)
            if status == 200 and text:
                bal = int(json.loads(text).get("result", "0x0"), 16) / (10**decimals)
                if bal and bal > 0:
                    return (label, addr, bal)
        except Exception as e:
            logger.debug(f"[{label}] {e}")
    return None


async def check_usdt_evm(session, addr, token_key: str):
    rpc, contract, decimals = USDT_CONTRACTS[token_key]
    sem_key = "eth" if token_key == "USDT_ETH" else ("bsc" if token_key == "USDT_BSC" else "polygon")
    async with PROVIDER_SEMAPHORES[sem_key]:
        try:
            data_call = "0x70a08231" + addr[2:].lower().zfill(64)
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_call",
                "params": [{"to": contract, "data": data_call}, "latest"],
            }
            status, text = await _fetch_with_retries(session, "POST", rpc, json=payload)
            if status == 200 and text:
                result = json.loads(text).get("result") or "0x0"
                if result in ("0x", "0x0", None):
                    return None
                bal = int(result, 16) / (10**decimals)
                if bal and bal > 0:
                    return (token_key, addr, bal)
        except Exception as e:
            logger.debug(f"[{token_key}] {e}")
    return None


async def check_btc(session, addr):
    async with PROVIDER_SEMAPHORES["btc"]:
        try:
            status, text = await _fetch_with_retries(session, "GET", PROVIDERS["btc"][0] + addr)
            if status == 200 and text is not None:
                try:
                    bal = int(text.strip()) / 10**8
                except Exception:
                    bal = 0
                if bal and bal > 0:
                    return ("BTC", addr, bal)
        except Exception as e:
            logger.debug(f"[BTC] {e}")
    return None


async def check_tron_all(session, addr) -> list:
    hits = []
    async with PROVIDER_SEMAPHORES["tron"]:
        try:
            status, text = await _fetch_with_retries(session, "GET", PROVIDERS["tron"][0] + addr)
            if status != 200 or not text:
                return hits
            data = json.loads(text)
            rows = data.get("data") or []
            if not rows:
                return hits
            acc = rows[0]
            raw_trx = acc.get("balance") or 0
            try:
                trx_bal = int(raw_trx) / 10**6
            except Exception:
                trx_bal = 0
            if trx_bal > 0:
                hits.append(("TRX", addr, trx_bal))
            for token in acc.get("trc20") or []:
                if not isinstance(token, dict):
                    continue
                for contract, raw in token.items():
                    try:
                        raw_i = int(str(raw))
                    except Exception:
                        continue
                    if raw_i <= 0:
                        continue
                    if contract in TRC20_KNOWN:
                        name, decimals = TRC20_KNOWN[contract]
                        hits.append((name, addr, raw_i / (10**decimals)))
                    else:
                        short = contract[:6] + "…" + contract[-4:]
                        hits.append((f"TRC20_{short}", addr, raw_i / 10**6))
        except Exception as e:
            logger.debug(f"[TRON] {addr}: {e}")
    return hits


def _derive_addrs(seed_bytes, acct: int, idx: int, change):
    b84 = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(acct).Change(change).AddressIndex(idx)
    b44_btc = Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(acct).Change(change).AddressIndex(idx)
    eth = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(acct).Change(change).AddressIndex(idx)
    sol = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(acct).Change(change).AddressIndex(idx)
    trx = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(acct).Change(change).AddressIndex(idx)
    return {
        "btc_sgw": b84.PublicKey().ToAddress(),
        "btc_leg": b44_btc.PublicKey().ToAddress(),
        "eth": eth.PublicKey().ToAddress(),
        "sol": sol.PublicKey().ToAddress(),
        "trx": trx.PublicKey().ToAddress(),
    }


async def _check_all_chains(session, addrs) -> list:
    evm = addrs["eth"]
    results = await asyncio.gather(
        check_tron_all(session, addrs["trx"]),
        check_evm_native(session, evm, "ETH"),
        check_evm_native(session, evm, "BNB"),
        check_evm_native(session, evm, "MATIC"),
        check_usdt_evm(session, evm, "USDT_ETH"),
        check_usdt_evm(session, evm, "USDT_BSC"),
        check_usdt_evm(session, evm, "USDT_POLYGON"),
        check_btc(session, addrs["btc_sgw"]),
        check_btc(session, addrs["btc_leg"]),
        check_sol(session, addrs["sol"]),
        return_exceptions=True,
    )
    hits = []
    for r in results:
        if isinstance(r, Exception) or not r:
            continue
        if isinstance(r, list):
            hits.extend(r)
        else:
            hits.append(r)
    return hits


async def check_seed_params(session, seed: str, accounts: int = None, indexes: int = None, early_stop: bool = None):
    accounts = accounts if accounts is not None else SCAN_ACCOUNTS
    indexes = indexes if indexes is not None else SCAN_ADDRESSES
    early_stop = EARLY_STOP if early_stop is None else early_stop
    try:
        seed_bytes = Bip39SeedGenerator(seed).Generate()
    except Exception as e:
        logger.error(f"Derivacao: {e}")
        return None

    changes = (Bip44Changes.CHAIN_EXT, Bip44Changes.CHAIN_INT)
    found = []
    for acct in range(max(1, accounts)):
        for idx in range(max(1, indexes)):
            for change in changes:
                try:
                    addrs = _derive_addrs(seed_bytes, acct, idx, change)
                    hits = await _check_all_chains(session, addrs)
                    if hits:
                        found.extend(hits)
                        if early_stop:
                            return (seed, found)
                except Exception as e:
                    logger.debug(f"path {acct}/{idx}: {e}")
                    continue
    return (seed, found) if found else None


async def check_balance_master(type, value, session=None):
    async def _run(sess):
        if type == "SEED":
            return await check_seed_params(sess, value)
        if type == "ADDR_TRON" or (isinstance(value, str) and value.startswith("T") and len(value) == 34):
            hits = await check_tron_all(sess, value)
            return (value, hits) if hits else None
        if type == "ADDR_ETH" or (isinstance(value, str) and value.startswith("0x") and len(value) == 42):
            hits = []
            for item in await asyncio.gather(
                check_evm_native(sess, value, "ETH"),
                check_evm_native(sess, value, "BNB"),
                check_evm_native(sess, value, "MATIC"),
                check_usdt_evm(sess, value, "USDT_ETH"),
                check_usdt_evm(sess, value, "USDT_BSC"),
                check_usdt_evm(sess, value, "USDT_POLYGON"),
            ):
                if item:
                    hits.append(item)
            return (value, hits) if hits else None
        if type == "ADDR_BTC" or (isinstance(value, str) and (value.startswith("bc1") or value.startswith(("1", "3")))):
            r = await check_btc(sess, value)
            return (value, [r]) if r else None
        r = await check_sol(sess, value)
        return (value, [r]) if r else None

    if session is not None:
        return await _run(session)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=CHECK_CONCURRENCY)) as sess:
        return await _run(sess)


async def check_seeds_bulk(seeds: list[str], workers: int = 20):
    sem = asyncio.Semaphore(max(1, workers))
    queue: asyncio.Queue = asyncio.Queue()
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=CHECK_CONCURRENCY, ttl_dns_cache=300)
    ) as session:
        async def worker(seed: str):
            async with sem:
                try:
                    res = await check_seed_params(session, seed)
                    await queue.put(("ok", seed, res))
                except Exception as e:
                    logger.exception(f"bulk seed error: {e}")
                    await queue.put(("err", seed, e))

        tasks = [asyncio.create_task(worker(s)) for s in seeds]
        done = 0
        total = len(seeds)
        while done < total:
            kind, seed, payload = await queue.get()
            done += 1
            if kind == "ok":
                yield seed, payload, None
            else:
                yield seed, None, payload
        await asyncio.gather(*tasks, return_exceptions=True)
