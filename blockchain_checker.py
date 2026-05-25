import asyncio
import aiohttp
import json
import logging
import random

logger = logging.getLogger(__name__)
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins, Bip84, Bip84Coins, Bip39MnemonicValidator,
    Bip32Utils
)

# ── ULTRA SPEED & ASSERTIVENESS TUNABLES ────────────────────────────────────
REQUEST_TIMEOUT   = 10          # Tempo limite para cada requisição RPC
SEED_TIMEOUT      = 120         # Tempo limite total para verificar uma seed
MAX_CONCURRENT_REQUESTS = 10    # Número de requisições simultâneas
GAP_LIMIT = 10                  # Número de endereços a verificar por conta
MAX_ACCOUNTS = 3                # Número de contas a verificar
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

RPC_URLS = {
    "BSC": ["https://bsc-dataseed.binance.org/", "https://bsc-dataseed1.defibit.io/", "https://bsc-dataseed1.ninicoin.io/"],
    "POLYGON": ["https://polygon-rpc.com/", "https://rpc-mainnet.maticvigil.com/", "https://matic-mainnet.chainstacklabs.com/"],
    "ETH": ["https://cloudflare-eth.com/", "https://eth-mainnet.public.blastapi.io/"]
}

USDT_CONTRACTS = {
    "ETH": "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "BSC": "0x55d398326f99059ff775485246999027b3197955",
    "POLYGON": "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"
}
# ────────────────────────────────────────────────────────────────────────────

semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def _rpc_call(session, urls, method, params):
    async with semaphore:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        shuffled_urls = list(urls)
        random.shuffle(shuffled_urls)
        for url in shuffled_urls:
            try:
                async with session.post(url, json=payload, timeout=REQUEST_TIMEOUT) as res:
                    if res.status == 200:
                        data = await res.json()
                        if 'result' in data: return data
                    elif res.status == 429:
                        logger.warning(f"RPC {url} retornou status 429 (Too Many Requests) para {method}")
                        await asyncio.sleep(random.uniform(2, 5)) # Espera e tenta outro RPC
                    else:
                        logger.warning(f"RPC {url} retornou status {res.status} para {method}")
            except asyncio.TimeoutError:
                logger.warning(f"Timeout ao conectar com RPC {url} para {method}")
            except aiohttp.ClientError as e:
                logger.warning(f"Erro de conexão com RPC {url} para {method}: {e}")
            except json.JSONDecodeError:
                logger.warning(f"Erro ao decodificar JSON do RPC {url} para {method}")
            except Exception as e:
                logger.error(f"Erro inesperado no RPC {url} para {method}: {e}")
        return None

async def get_universal_addresses(seed_phrase):
    try:
        seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
    except Exception: return []
    
    addr_map = []
    for account_idx in range(MAX_ACCOUNTS):
        for address_idx in range(GAP_LIMIT):
            # BTC (BIP-44, BIP-49, BIP-84)
            try:
                addr_map.append(("BTC", "Native", Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()))
                addr_map.append(("BTC", "P2SH-SegWit", Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()))
                addr_map.append(("BTC", "P2PKH", Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()))
            except Exception: pass

            # EVM (ETH, BSC, POLYGON) - BIP-44
            try:
                eth_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()
                addr_map.append(("EVM", "ADDR", eth_addr))
            except Exception: pass

            # Tron (Múltiplos Caminhos)
            try:
                # 1. Padrão BIP-44 (m/44'/195'/0'/0/0)
                trx_addr_std = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()
                addr_map.append(("TRX", "STD", trx_addr_std))
                
                # 2. Alternativo (m/44'/195'/0'/0) - Comum em algumas carteiras
                bip32_ctx = Bip32Utils.FromSeed(seed_bytes).DerivePath(f"m/44'/195'/{account_idx}'/0")
                trx_addr_alt = Bip44.FromPublicKey(bip32_ctx.PublicKey().Raw().ToBytes(), Bip44Coins.TRON).PublicKey().ToAddress()
                addr_map.append(("TRX", "ALT", trx_addr_alt))
                
                # 3. Trust Wallet Style (Tron usando caminho de ETH: m/44'/60'/0'/0/index)
                eth_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx)
                trx_addr_trust = Bip44.FromPublicKey(eth_ctx.PublicKey().Raw().ToBytes(), Bip44Coins.TRON).PublicKey().ToAddress()
                addr_map.append(("TRX", "TRUST", trx_addr_trust))
            except Exception: pass

    return addr_map

async def check_btc(session, addr):
    async with semaphore:
        try:
            # Tenta Blockstream (mais confiável para bc1) e Blockchain.info
            async with session.get(f"https://blockstream.info/api/address/{addr}", timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200:
                    d = await res.json()
                    bal = (d["chain_stats"]["funded_txo_sum"] - d["chain_stats"]["spent_txo_sum"]) / 10**8
                    if bal > 0: return [("BTC", addr, bal)]
        except Exception: pass
        try:
            async with session.get(f"https://blockchain.info/q/addressbalance/{addr}", timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200:
                    bal = int(await res.text()) / 10**8
                    if bal > 0: return [("BTC", addr, bal)]
        except Exception: pass
        return []

async def check_evm_full(session, addr):
    results = []
    for net, urls in RPC_URLS.items():
        data = await _rpc_call(session, urls, "eth_getBalance", [addr, "latest"])
        if data and 'result' in data:
            bal = int(data['result'], 16) / 10**18
            if bal > 0: results.append((net, addr, bal))
        
        contract = USDT_CONTRACTS.get(net)
        if contract:
            call_data = "0x70a08231" + addr[2:].zfill(64)
            t_data = await _rpc_call(session, urls, "eth_call", [{"to": contract, "data": call_data}, "latest"])
            if t_data and 'result' in t_data and t_data['result'] != '0x':
                t_bal = int(t_data['result'], 16) / 10**6
                if t_bal > 0: results.append((f"USDT_{net}", addr, t_bal))
    return results

async def check_trx(session, addr):
    async with semaphore:
        results = []
        # Tenta TronGrid e se falhar (429), tenta a API pública da Tron
        for api_url in [f"https://api.trongrid.io/v1/accounts/{addr}", f"https://api.tronstack.io/v1/accounts/{addr}"]:
            try:
                async with session.get(api_url, timeout=REQUEST_TIMEOUT) as res:
                    if res.status == 200:
                        data = await res.json()
                        if data.get('data'):
                            acc = data['data'][0]
                            bal_trx = acc.get('balance', 0) / 10**6
                            if bal_trx > 0: results.append(("TRX", addr, bal_trx))
                            
                            for token_data in acc.get('trc20', []):
                                for contract, val in token_data.items():
                                    try:
                                        token_bal = float(val) / 10**6
                                        if token_bal > 0:
                                            symbol = "USDT" if contract == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' else "TRC20"
                                            results.append((symbol, addr, token_bal))
                                    except: continue
                            return results # Sucesso, sai do loop de APIs
            except Exception: continue
        return results

async def check_balance_all(seed):
    seed = seed.strip()
    if not seed: return None
    addr_map = await get_universal_addresses(seed)
    if not addr_map: return None

    async with aiohttp.ClientSession() as session:
        tasks = []
        for coin, label, addr in addr_map:
            if coin == "BTC": tasks.append(check_btc(session, addr))
            elif coin == "EVM": tasks.append(check_evm_full(session, addr))
            elif coin == "TRX": tasks.append(check_trx(session, addr))
        
        try:
            raw = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=SEED_TIMEOUT)
        except Exception: raw = []

    found = []
    for item in raw:
        if item and not isinstance(item, Exception):
            if isinstance(item, list): found.extend(item)
            else: found.append(item)
    
    if not found: return None
    
    unique_found = []
    seen_results = set()
    for coin, addr, bal in found:
        key = (coin, addr)
        if key not in seen_results:
            unique_found.append((coin, addr, bal))
            seen_results.add(key)
            
    return (seed, unique_found)
