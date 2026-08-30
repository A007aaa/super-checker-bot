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
PER_PROVIDER_LIMIT = int(os.getenv("PER_PROVIDER_LIMIT", "25"))
SCAN_ADDRESSES = int(os.getenv("SCAN_ADDRESSES", "50"))
SCAN_ACCOUNTS = int(os.getenv("SCAN_ACCOUNTS", "5"))
CHECK_TIMEOUT = int(os.getenv("CHECK_TIMEOUT", "20"))
CHECK_RETRIES = int(os.getenv("CHECK_RETRIES", "2"))
RETRY_BACKOFF_BASE = float(os.getenv("RETRY_BACKOFF_BASE", "1.4"))
EARLY_STOP = os.getenv("EARLY_STOP", "true").lower() in ("1", "true", "yes")

PROVIDERS = {
    "eth": [os.getenv("ETH_RPC", "https://cloudflare-eth.com/")],
    "sol": [os.getenv("SOL_RPC", "https://api.mainnet-beta.solana.com")],
    "btc": [os.getenv("BTC_API", "https://blockchain.info/q/addressbalance/")],
    "tron": [os.getenv("TRON_API", "https://api.trongrid.io/v1/accounts/")],
}

PROVIDER_SEMAPHORES = {k: asyncio.Semaphore(PER_PROVIDER_LIMIT) for k in PROVIDERS}


def preview_addresses(seed: str) -> dict:
    """Endereços path m/44'/coin'/0'/0/0 para diagnóstico."""
    seed_bytes = Bip39SeedGenerator(seed).Generate()
    return _derive_addrs(seed_bytes, 0, 0, Bip44Changes.CHAIN_EXT)


async def _fetch_with_retries(session, method: str, url: str, **kwargs):
    last_exc = None
    for attempt in range(1, CHECK_RETRIES + 2):
        try:
            timeout = aiohttp.ClientTimeout(total=CHECK_TIMEOUT)
            async with session.request(method, url, timeout=timeout, **kwargs) as res:
                try:
                    text = await res.text()
                except Exception:
                    text = None
                return res.status, text
        except Exception as e:
            last_exc = e
            if attempt <= CHECK_RETRIES + 1:
                backoff = (RETRY_BACKOFF_BASE ** (attempt - 1)) * (0.4 + random.random() * 0.4)
                await asyncio.sleep(backoff)
    raise last_exc


async def check_sol(session, addr):
    async with PROVIDER_SEMAPHORES["sol"]:
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
            status, text = await _fetch_with_retries(
                session, "POST", PROVIDERS["sol"][0], json=payload
            )
            if status == 200 and text:
                data = json.loads(text)
                bal = data.get("result", {}).get("value", 0) / 10**9
                if bal and bal > 0:
                    logger.info(f"   💰 [SOL] {bal} @ {addr}")
                    return ("SOL", addr, bal)
        except Exception as e:
            logger.debug(f"   ❌ [SOL] {e}")
    return None


async def check_eth(session, addr):
    async with PROVIDER_SEMAPHORES["eth"]:
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getBalance",
                "params": [addr, "latest"],
            }
            status, text = await _fetch_with_retries(
                session, "POST", PROVIDERS["eth"][0], json=payload
            )
            if status == 200 and text:
                data = json.loads(text)
                bal = int(data.get("result", "0x0"), 16) / 10**18
                if bal and bal > 0:
                    logger.info(f"   💰 [ETH] {bal} @ {addr}")
                    return ("ETH", addr, bal)
        except Exception as e:
            logger.debug(f"   ❌ [ETH] {e}")
    return None


async def check_usdt_eth(session, addr):
    async with PROVIDER_SEMAPHORES["eth"]:
        try:
            usdt = "0xdac17f958d2ee523a2206206994597c13d831ec7"
            data_call = "0x70a08231" + addr[2:].lower().zfill(64)
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_call",
                "params": [{"to": usdt, "data": data_call}, "latest"],
            }
            status, text = await _fetch_with_retries(
                session, "POST", PROVIDERS["eth"][0], json=payload
            )
            if status == 200 and text:
                data = json.loads(text)
                bal = int(data.get("result", "0x0"), 16) / 10**6
                if bal and bal > 0:
                    logger.info(f"   💰 [USDT_ETH] {bal} @ {addr}")
                    return ("USDT_ETH", addr, bal)
        except Exception as e:
            logger.debug(f"   ❌ [USDT_ETH] {e}")
    return None


async def check_btc(session, addr):
    async with PROVIDER_SEMAPHORES["btc"]:
        try:
            status, text = await _fetch_with_retries(
                session, "GET", PROVIDERS["btc"][0] + addr
            )
            if status == 200 and text is not None:
                try:
                    bal = int(text.strip()) / 10**8
                except Exception:
                    bal = 0
                if bal and bal > 0:
                    logger.info(f"   💰 [BTC] {bal} @ {addr}")
                    return ("BTC", addr, bal)
        except Exception as e:
            logger.debug(f"   ❌ [BTC] {e}")
    return None


async def check_trx(session, addr):
    async with PROVIDER_SEMAPHORES["tron"]:
        try:
            status, text = await _fetch_with_retries(
                session, "GET", PROVIDERS["tron"][0] + addr
            )
            if status == 200 and text:
                data = json.loads(text)
                if data.get("data"):
                    acc = data["data"][0]
                    trx_bal = acc.get("balance", 0) / 10**6
                    if trx_bal and trx_bal > 0:
                        logger.info(f"   💰 [TRX] {trx_bal} @ {addr}")
                        return ("TRX", addr, trx_bal)
        except Exception as e:
            logger.debug(f"   ❌ [TRX] {e}")
    return None


async def check_usdt_trx(session, addr):
    async with PROVIDER_SEMAPHORES["tron"]:
        try:
            status, text = await _fetch_with_retries(
                session, "GET", PROVIDERS["tron"][0] + addr
            )
            if status == 200 and text:
                data = json.loads(text)
                if data.get("data"):
                    acc = data["data"][0]
                    for token in acc.get("trc20", []):
                        try:
                            u_bal = None
                            if isinstance(token, dict):
                                if token.get("tokenId") == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t":
                                    u_bal = float(token["balance"]) / 10**6
                                else:
                                    for k, v in token.items():
                                        if "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t" in str(k):
                                            u_bal = float(v) / 10**6
                                            break
                            if u_bal and u_bal > 0:
                                logger.info(f"   💰 [USDT_TRX] {u_bal} @ {addr}")
                                return ("USDT_TRX", addr, u_bal)
                        except Exception:
                            continue
        except Exception as e:
            logger.debug(f"   ❌ [USDT_TRX] {e}")
    return None


def _derive_addrs(seed_bytes, acct: int, idx: int, change):
    b84 = (
        Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN)
        .Purpose()
        .Coin()
        .Account(acct)
        .Change(change)
        .AddressIndex(idx)
    )
    b44_btc = (
        Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN)
        .Purpose()
        .Coin()
        .Account(acct)
        .Change(change)
        .AddressIndex(idx)
    )
    eth = (
        Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM)
        .Purpose()
        .Coin()
        .Account(acct)
        .Change(change)
        .AddressIndex(idx)
    )
    sol = (
        Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)
        .Purpose()
        .Coin()
        .Account(acct)
        .Change(change)
        .AddressIndex(idx)
    )
    trx = (
        Bip44.FromSeed(seed_bytes, Bip44Coins.TRON)
        .Purpose()
        .Coin()
        .Account(acct)
        .Change(change)
        .AddressIndex(idx)
    )
    return {
        "btc_sgw": b84.PublicKey().ToAddress(),
        "btc_leg": b44_btc.PublicKey().ToAddress(),
        "eth": eth.PublicKey().ToAddress(),
        "sol": sol.PublicKey().ToAddress(),
        "trx": trx.PublicKey().ToAddress(),
    }


async def _check_all_chains(session, addrs) -> list:
    coros = [
        check_eth(session, addrs["eth"]),
        check_usdt_eth(session, addrs["eth"]),
        check_btc(session, addrs["btc_sgw"]),
        check_btc(session, addrs["btc_leg"]),
        check_sol(session, addrs["sol"]),
        check_trx(session, addrs["trx"]),
        check_usdt_trx(session, addrs["trx"]),
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)
    hits = []
    for r in results:
        if r is None or isinstance(r, Exception):
            continue
        hits.append(r)
    return hits


async def check_seed_params(
    session,
    seed: str,
    accounts: int = None,
    indexes: int = None,
    early_stop: bool = None,
):
    accounts = accounts if accounts is not None else SCAN_ACCOUNTS
    indexes = indexes if indexes is not None else SCAN_ADDRESSES
    early_stop = EARLY_STOP if early_stop is None else early_stop

    try:
        seed_bytes = Bip39SeedGenerator(seed).Generate()
    except Exception as e:
        logger.error(f"   ❌ Derivação: {e}")
        return None

    changes = (Bip44Changes.CHAIN_EXT, Bip44Changes.CHAIN_INT)
    total_combos = max(1, accounts) * max(1, indexes) * len(changes)
    logger.info(
        f"   📡 Varrendo {total_combos} paths "
        f"(acct 0..{accounts-1}, idx 0..{indexes-1}, ext+int)"
    )

    found = []

    for acct in range(max(1, accounts)):
        for idx in range(max(1, indexes)):
            for change in changes:
                try:
                    addrs = _derive_addrs(seed_bytes, acct, idx, change)
                    hits = await _check_all_chains(session, addrs)
                    if hits:
                        found.extend(hits)
                        logger.info(
                            f"   ✅ Path acct={acct} idx={idx} {change.name}: "
                            f"{[h[0] for h in hits]}"
                        )
                        if early_stop:
                            return (seed, found)
                except Exception as e:
                    logger.debug(f"   ⚠️ path {acct}/{idx}: {e}")
                    continue

    if found:
        return (seed, found)

    try:
        a0 = _derive_addrs(seed_bytes, 0, 0, Bip44Changes.CHAIN_EXT)
        logger.info(
            f"   ⚪ Sem saldo. ETH[0]={a0['eth']} SOL[0]={a0['sol']} TRX[0]={a0['trx']}"
        )
    except Exception:
        pass
    return None


async def check_balance_master(type, value):
    logger.info(f"🔍 Verificação: tipo={type}")
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=CHECK_CONCURRENCY)
    ) as session:
        if type == "SEED":
            return await check_seed_params(session, value)

        if type == "KEY_SOL":
            r = await check_sol(session, value)
            return (value, [r]) if r else None
        if type == "KEY_HEX":
            addr = value if value.startswith("0x") else f"0x{value}"
            hits = [
                x
                for x in await asyncio.gather(
                    check_eth(session, addr), check_usdt_eth(session, addr)
                )
                if x
            ]
            return (value, hits) if hits else None
        if type == "ADDR_ETH":
            hits = [
                x
                for x in await asyncio.gather(
                    check_eth(session, value), check_usdt_eth(session, value)
                )
                if x
            ]
            return (value, hits) if hits else None
        if type == "ADDR_BTC":
            r = await check_btc(session, value)
            return (value, [r]) if r else None
        if type == "ADDR_TRON":
            hits = [
                x
                for x in await asyncio.gather(
                    check_trx(session, value), check_usdt_trx(session, value)
                )
                if x
            ]
            return (value, hits) if hits else None
        if type == "ADDR_SOL":
            r = await check_sol(session, value)
            return (value, [r]) if r else None

        if value.startswith("0x") and len(value) == 42:
            hits = [
                x
                for x in await asyncio.gather(
                    check_eth(session, value), check_usdt_eth(session, value)
                )
                if x
            ]
            return (value, hits) if hits else None
        if value.startswith("T") and len(value) == 34:
            hits = [
                x
                for x in await asyncio.gather(
                    check_trx(session, value), check_usdt_trx(session, value)
                )
                if x
            ]
            return (value, hits) if hits else None
        if value.startswith("bc1") or value.startswith(("1", "3")):
            r = await check_btc(session, value)
            return (value, [r]) if r else None
        r = await check_sol(session, value)
        return (value, [r]) if r else None
