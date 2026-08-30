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

# Tokens TRC-20 conhecidos (contrato -> (nome, decimals))
TRC20_KNOWN = {
    "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t": ("USDT_TRX", 6),  # USDT
    "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8": ("USDC_TRX", 6),  # USDC
    "TKkeiboTkxXKJpbmVFbv4a8ov5rAfRDMf9": ("BTT_TRX", 18),
    "TCFLL5dx5ZJdKnWuesXxi1VPwjLVmWZZy9": ("JST_TRX", 18),
    "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7": ("WIN_TRX", 6),
}

PROVIDERS = {
    "eth": [os.getenv("ETH_RPC", "https://cloudflare-eth.com/")],
    "sol": [os.getenv("SOL_RPC", "https://api.mainnet-beta.solana.com")],
    "btc": [os.getenv("BTC_API", "https://blockchain.info/q/addressbalance/")],
    "tron": [os.getenv("TRON_API", "https://api.trongrid.io/v1/accounts/")],
}

PROVIDER_SEMAPHORES = {k: asyncio.Semaphore(PER_PROVIDER_LIMIT) for k in PROVIDERS}

# Header opcional se tiver TRON_API_KEY no Railway (melhora rate limit)
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


async def check_tron_all(session, addr) -> list:
    """
    Uma chamada TronGrid: TRX nativo + TODOS os TRC-20 com saldo.
    Retorna lista de tuples (coin, addr, bal).
    """
    hits = []
    async with PROVIDER_SEMAPHORES["tron"]:
        try:
            status, text = await _fetch_with_retries(
                session, "GET", PROVIDERS["tron"][0] + addr
            )
            if status != 200 or not text:
                logger.debug(f"   ⚠️ [TRON] status={status} body={str(text)[:120]}")
                return hits

            data = json.loads(text)
            rows = data.get("data") or []
            if not rows:
                # conta nunca ativada na rede = saldo zero
                return hits

            acc = rows[0]

            # TRX nativo (sun -> TRX). balance pode ser None
            raw_trx = acc.get("balance") or 0
            try:
                trx_bal = int(raw_trx) / 10**6
            except Exception:
                trx_bal = 0
            if trx_bal > 0:
                logger.info(f"   💰 [TRX] {trx_bal} @ {addr}")
                hits.append(("TRX", addr, trx_bal))

            # TRC-20: lista de dicts {"TContract...": "raw_amount"}
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
                        bal = raw_i / (10**decimals)
                        logger.info(f"   💰 [{name}] {bal} @ {addr}")
                        hits.append((name, addr, bal))
                    else:
                        # token desconhecido: mostra raw / 1e6 como heurística
                        # (maioria USDT-like usa 6 casas)
                        bal = raw_i / 10**6
                        short = contract[:6] + "…" + contract[-4:]
                        name = f"TRC20_{short}"
                        logger.info(f"   💰 [{name}] raw={raw_i} (~{bal}) @ {addr}")
                        hits.append((name, addr, bal))

        except Exception as e:
            logger.error(f"   ❌ [TRON] {addr}: {e}")
    return hits


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
    # TRON primeiro (prioridade do usuário)
    tron_hits = await check_tron_all(session, addrs["trx"])

    coros = [
        check_eth(session, addrs["eth"]),
        check_usdt_eth(session, addrs["eth"]),
        check_btc(session, addrs["btc_sgw"]),
        check_btc(session, addrs["btc_leg"]),
        check_sol(session, addrs["sol"]),
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)
    hits = list(tron_hits)
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
        f"(acct 0..{accounts-1}, idx 0..{indexes-1}, ext+int) — TRON prioritário"
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
            f"   ⚪ Sem saldo. TRX[0]={a0['trx']} ETH[0]={a0['eth']} SOL[0]={a0['sol']}"
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
            hits = await check_tron_all(session, value)
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
            hits = await check_tron_all(session, value)
            return (value, hits) if hits else None
        if value.startswith("bc1") or value.startswith(("1", "3")):
            r = await check_btc(session, value)
            return (value, [r]) if r else None
        r = await check_sol(session, value)
        return (value, [r]) if r else None
