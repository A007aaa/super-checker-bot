import asyncio
import aiohttp
import logging
import os
import math
import random
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip84, Bip84Coins
)

logger = logging.getLogger(__name__)

# Configuráveis via ENV
CHECK_CONCURRENCY = int(os.getenv('CHECK_CONCURRENCY', '20'))  # concurrent network calls
SCAN_ADDRESSES = int(os.getenv('SCAN_ADDRESSES', '20'))        # number of address indexes to scan per account
SCAN_ACCOUNTS = int(os.getenv('SCAN_ACCOUNTS', '1'))           # number of account indices to scan (0..SCAN_ACCOUNTS-1)
CHECK_TIMEOUT = int(os.getenv('CHECK_TIMEOUT', '30'))         # seconds per HTTP request
CHECK_RETRIES = int(os.getenv('CHECK_RETRIES', '2'))          # number of retries on transient errors
RETRY_BACKOFF_BASE = float(os.getenv('RETRY_BACKOFF_BASE', '1.5'))  # exponential backoff base

semaphore = asyncio.Semaphore(CHECK_CONCURRENCY)

async def _fetch_with_retries(session, method: str, url: str, **kwargs):
    """Perform HTTP request with retries and exponential backoff. Returns response object or raises.
    kwargs passed to session.request (json, timeout, params, data, etc.)
    """
    last_exc = None
    for attempt in range(1, CHECK_RETRIES + 2):  # retries + first try
        try:
            timeout = aiohttp.ClientTimeout(total=CHECK_TIMEOUT)
            async with session.request(method, url, timeout=timeout, **kwargs) as res:
                # read body safely for logging if needed
                try:
                    text = await res.text()
                except Exception:
                    text = None
                logger.debug(f"HTTP {method} {url} [attempt {attempt}] -> status {res.status}")
                return res, text
        except asyncio.TimeoutError as e:
            logger.warning(f"   ⏱️ Timeout {method} {url} attempt {attempt}/{CHECK_RETRIES+1}")
            last_exc = e
        except aiohttp.ClientError as e:
            logger.warning(f"   ⚠️ HTTP client error on {method} {url} attempt {attempt}: {e}")
            last_exc = e
        except Exception as e:
            logger.error(f"   ❌ Unexpected error on {method} {url} attempt {attempt}: {e}")
            last_exc = e

        # backoff before next attempt
        if attempt <= CHECK_RETRIES + 1:
            backoff = (RETRY_BACKOFF_BASE ** (attempt - 1)) * (0.5 + random.random() * 0.5)
            await asyncio.sleep(backoff)

    # exhausted
    raise last_exc

async def check_sol(session, addr):
    async with semaphore:
        try:
            logger.debug(f"   🌐 [SOL] Verificando endereço: {addr}")
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
            res, text = await _fetch_with_retries(session, 'POST', "https://api.mainnet-beta.solana.com", json=payload)
            if res.status == 200:
                try:
                    data = await res.json()
                except Exception:
                    data = {}
                bal = data.get('result', {}).get('value', 0) / 10**9
                if bal > 0:
                    logger.info(f"   💰 [SOL] Saldo encontrado: {bal} SOL em {addr}")
                    return (("SOL", addr, bal),)
                else:
                    logger.debug(f"   ⚪ [SOL] Saldo zero em {addr}")
            else:
                logger.debug(f"   ⚠️ [SOL] Response {res.status} for {addr} - body: {text}")
        except Exception as e:
            logger.error(f"   ❌ [SOL] Erro ao verificar {addr}: {e}")
    return ()

async def check_eth_usdt(session, addr):
    async with semaphore:
        results = []
        try:
            logger.debug(f"   🌐 [ETH] Verificando endereço: {addr}")
            # ETH Balance
            payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [addr, "latest"]}
            res, text = await _fetch_with_retries(session, 'POST', "https://cloudflare-eth.com/", json=payload)
            if res.status == 200:
                try:
                    data = await res.json()
                except Exception:
                    data = {}
                bal = int(data.get('result', '0x0'), 16) / 10**18
                if bal > 0:
                    logger.info(f"   💰 [ETH] Saldo encontrado: {bal} ETH em {addr}")
                    results.append(("ETH", addr, bal))
                else:
                    logger.debug(f"   ⚪ [ETH] Saldo zero em {addr}")
            else:
                logger.debug(f"   ⚠️ [ETH] Response {res.status} for {addr} - body: {text}")

            # USDT (ERC20)
            logger.debug(f"   🌐 [USDT_ETH] Verificando endereço: {addr}")
            usdt_contract = "0xdac17f958d2ee523a2206206994597c13d831ec7"
            # keccak-based call: balanceOf(address) selector + padded address
            data_call = "0x70a08231" + addr[2:].lower().zfill(64)
            payload_u = {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": usdt_contract, "data": data_call}, "latest"]}
            res_u, text_u = await _fetch_with_retries(session, 'POST', "https://cloudflare-eth.com/", json=payload_u)
            if res_u.status == 200:
                try:
                    data = await res_u.json()
                except Exception:
                    data = {}
                u_bal = int(data.get('result', '0x0'), 16) / 10**6
                if u_bal > 0:
                    logger.info(f"   💰 [USDT_ETH] Saldo encontrado: {u_bal} USDT em {addr}")
                    results.append(("USDT_ETH", addr, u_bal))
                else:
                    logger.debug(f"   ⚪ [USDT_ETH] Saldo zero em {addr}")
            else:
                logger.debug(f"   ⚠️ [USDT_ETH] Response {res_u.status} for {addr} - body: {text_u}")

        except Exception as e:
            logger.error(f"   ❌ [ETH/USDT] Erro ao verificar {addr}: {e}")
        return tuple(results)

async def check_btc(session, addr):
    async with semaphore:
        try:
            logger.debug(f"   🌐 [BTC] Verificando endereço: {addr}")
            res, text = await _fetch_with_retries(session, 'GET', f"https://blockchain.info/q/addressbalance/{addr}")
            if res.status == 200:
                try:
                    bal = int(text) / 10**8
                except Exception:
                    bal = 0
                if bal > 0:
                    logger.info(f"   💰 [BTC] Saldo encontrado: {bal} BTC em {addr}")
                    return (("BTC", addr, bal),)
                else:
                    logger.debug(f"   ⚪ [BTC] Saldo zero em {addr}")
            else:
                logger.debug(f"   ⚠️ [BTC] Response {res.status} for {addr} - body: {text}")
        except Exception as e:
            logger.error(f"   ❌ [BTC] Erro ao verificar {addr}: {e}")
    return ()

async def check_tron_usdt(session, addr):
    async with semaphore:
        results = []
        try:
            logger.debug(f"   🌐 [TRX] Verificando endereço: {addr}")
            res, text = await _fetch_with_retries(session, 'GET', f"https://api.trongrid.io/v1/accounts/{addr}")
            if res.status == 200:
                try:
                    data = await res.json()
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
                        # token may be dict with tokenId/contract or mapping; attempt robust access
                        try:
                            # common structure: {'tokenId': '...', 'balance': '...'} or {contract: balance}
                            if isinstance(token, dict):
                                # try known contract key
                                if 'balance' in token and 'tokenId' in token and token.get('tokenId') == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t':
                                    u_bal = float(token['balance']) / 10**6
                                else:
                                    # fallback: search values
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
                    logger.debug(f"   ⚪ [TRX] Conta não encontrada / sem dados em {addr}")
            else:
                logger.debug(f"   ⚠️ [TRX] Response {res.status} for {addr} - body: {text}")
        except Exception as e:
            logger.error(f"   ❌ [TRX] Erro ao verificar {addr}: {e}")
        return tuple(results)

async def check_balance_master(type, value):
    logger.info(f"🔍 Iniciando verificação: tipo={type}")
    async with aiohttp.ClientSession() as session:
        addr_map = {} # {addr: (coin_type, check_function)}
        max_index = max(1, SCAN_ADDRESSES)
        max_accounts = max(1, SCAN_ACCOUNTS)

        if type == "SEED":
            try:
                seed_bytes = Bip39SeedGenerator(value).Generate()

                # Generate addresses across multiple accounts and indexes to increase recall
                for acct in range(max_accounts):
                    for idx in range(max_index):
                        try:
                            # 1. BTC Native Segwit (bc1...) - BIP84
                            b84 = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(acct).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx)
                            btc_segwit_addr = b84.PublicKey().ToAddress()
                            addr_map[btc_segwit_addr] = ("BTC_SEGWIT", check_btc)

                            # 2. BTC Legacy (1...) - BIP44
                            b44_btc = Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(acct).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx)
                            btc_legacy_addr = b44_btc.PublicKey().ToAddress()
                            addr_map[btc_legacy_addr] = ("BTC_LEGACY", check_btc)

                            # 3. ETH/USDT (0x...) - BIP44
                            eth = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(acct).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx)
                            eth_addr = eth.PublicKey().ToAddress()
                            addr_map[eth_addr] = ("ETH", check_eth_usdt)

                            # 4. SOL (Base58) - BIP44
                            sol = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(acct).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx)
                            sol_addr = sol.PublicKey().ToAddress()
                            addr_map[sol_addr] = ("SOL", check_sol)

                            # 5. TRX (T...) - BIP44
                            trx = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(acct).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx)
                            trx_addr = trx.PublicKey().ToAddress()
                            addr_map[trx_addr] = ("TRX", check_tron_usdt)

                            # debug logging of a sample of derived addresses to avoid log spam
                            if idx % max(1, max_index // 5) == 0 and acct == 0:
                                logger.debug(f"   📍 Sample derived addresses acct={acct} idx={idx}: BTC_SGW={btc_segwit_addr}, ETH={eth_addr}, SOL={sol_addr}, TRX={trx_addr}")

                        except Exception as e:
                            logger.debug(f"   ⚠️ Falha ao derivar para acct={acct} idx={idx}: {e}")

            except Exception as e:
                logger.error(f"   ❌ Erro na derivação de endereços: {e}")
                return None
        elif type == "KEY_SOL":
            # Chave privada Solana (Base58) → verificar apenas SOL
            addr_map[value] = ("KEY_SOL", check_sol)

        elif type == "KEY_HEX":
            # Chave privada Ethereum (hex) → verificar apenas ETH and USDT
            addr = value if value.startswith("0x") else f"0x{value}"
            addr_map[addr] = ("KEY_HEX", check_eth_usdt)

        elif type == "ADDR_ETH":
            # Endereço Ethereum direto → verificar ETH e USDT
            addr_map[value] = ("ADDR_ETH", check_eth_usdt)

        elif type == "ADDR_BTC":
            # Endereço Bitcoin direto → verificar BTC
            addr_map[value] = ("ADDR_BTC", check_btc)

        elif type == "ADDR_TRON":
            # Endereço Tron direto → verificar TRX e USDT
            addr_map[value] = ("ADDR_TRON", check_tron_usdt)

        elif type == "ADDR_SOL":
            # Endereço Solana direto → verificar SOL
            addr_map[value] = ("ADDR_SOL", check_sol)

        else:
            # Fallback: detectar pelo prefixo para tipos desconhecidos
            if value.startswith("0x") and len(value) == 42:
                addr_map[value] = ("ADDR_ETH", check_eth_usdt)
            elif value.startswith("T") and len(value) == 34:
                addr_map[value] = ("ADDR_TRON", check_tron_usdt)
            elif value.startswith("bc1") or value.startswith(("1", "3")):
                addr_map[value] = ("ADDR_BTC", check_btc)
            else:
                # Último fallback: tentar como endereço Solana
                addr_map[value] = ("ADDR_SOL", check_sol)

        if not addr_map:
            logger.info("⚪ Nenhum endereço para verificar")
            return None

        tasks = []
        for addr, (coin_type, check_func) in addr_map.items():
            tasks.append(check_func(session, addr))

        raw_results = await asyncio.gather(*tasks)
        
        # Achatar resultados (alguns retornam tuplas de tuplas)
        final_found = []
        for r in raw_results:
            if not r: continue
            if isinstance(r, (list, tuple)):
                final_found.extend(r)
            
        if final_found:
            balance_lines = " | ".join(f"{coin}: {bal}" for coin, _addr, bal in final_found)
            logger.info(f"✅ TOTAL: {len(final_found)} saldo(s) encontrado(s)")
            for coin, _addr, bal in final_found:
                logger.info(f"   💰 {coin}: {bal}")
            return (value, final_found)
        else:
            logger.info(f"⚪ TOTAL: nenhum saldo encontrado")
    return None
