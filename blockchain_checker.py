import asyncio
import aiohttp
import json
import logging
import random
import time
import hmac
import hashlib
import base64

logger = logging.getLogger(__name__)
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins, Bip84, Bip84Coins, Bip39MnemonicValidator,
    Bip32Utils
)

# ── ULTRA SPEED & ASSERTIVENESS TUNABLES ────────────────────────────────────
REQUEST_TIMEOUT   = 10          # Tempo limite para cada requisição RPC
SEED_TIMEOUT      = 120         # Tempo limite total para verificar uma seed
MAX_CONCURRENT_REQUESTS = 30    # Aumentado para Velocidade Máxima (Modo Agressivo)
GAP_LIMIT = 5                   # Reduzido para velocidade e estabilidade
MAX_ACCOUNTS = 1                # Focar na conta principal para evitar 429
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

RPC_URLS = {
    "BSC": [
        "https://bnb-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8",
        "https://bsc-dataseed.binance.org/",
        "https://rpc.ankr.com/bsc"
    ],
    "POLYGON": [
        "https://polygon-rpc.com/",
        "https://rpc.ankr.com/polygon"
    ],
    "ETH": [
        "https://eth-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8",
        "https://cloudflare-eth.com/",
        "https://rpc.ankr.com/eth"
    ],
    "SOL": [
        "https://solana-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8",
        "https://api.mainnet-beta.solana.com",
        "https://rpc.ankr.com/solana"
    ],
    "ARBITRUM": [
        "https://arb1.arbitrum.io/rpc",
        "https://rpc.ankr.com/arbitrum"
    ],
    "OPTIMISM": [
        "https://mainnet.optimism.io",
        "https://rpc.ankr.com/optimism"
    ],
    "AVALANCHE": [
        "https://api.avax.network/ext/bc/C/rpc",
        "https://rpc.ankr.com/avalanche"
    ],
    "FANTOM": [
        "https://rpc.ftm.tools/",
        "https://rpc.ankr.com/fantom"
    ]
}

USDT_CONTRACTS = {
    "ETH": "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "BSC": "0x55d398326f99059ff775485246999027b3197955",
    "POLYGON": "0xc2132d05d31c914a87c6611c10748aeb04b58e8f",
    "ARBITRUM": "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9",
    "OPTIMISM": "0x94b008aa21185010605a48c994c1d561c349aba3",
    "AVALANCHE": "0x9702230a8ea53601f5cd2dc00fdbc13d4df4a8c7",
    "FANTOM": "0x049d68029688eabf473097a2fc38ef61633a3c7a"
}
# ────────────────────────────────────────────────────────────────────────────

semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

# Blacklist temporária para RPCs com falha
rpc_blacklist = {}
BLACKLIST_TIME = 60 

# Cache em memória para evitar requisições duplicadas (Expira em 1 hora)
balance_cache = {}
CACHE_EXPIRY = 3600

async def _rpc_call(session, urls, method, params):
    # Gerar chave de cache para métodos de leitura
    cache_key = None
    if method in ["eth_getBalance", "eth_call", "getBalance", "getTokenAccountsByOwner"]:
        cache_key = f"{method}:{json.dumps(params)}:{urls[0]}"
        if cache_key in balance_cache:
            val, timestamp = balance_cache[cache_key]
            if time.time() - timestamp < CACHE_EXPIRY:
                return val
    async with semaphore:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        
        # Filtra URLs blacklisted e embaralha as restantes
        available_urls = [url for url in urls if url not in rpc_blacklist or (time.time() - rpc_blacklist[url]) > BLACKLIST_TIME]
        if not available_urls:
            logger.warning(f"Todas as URLs RPC para {method} estão na blacklist. Tentando novamente em breve.")
            await asyncio.sleep(5) # Espera 5 segundos
            available_urls = [url for url in urls if url not in rpc_blacklist or (time.time() - rpc_blacklist[url]) > BLACKLIST_TIME]
            if not available_urls: return None # Se ainda não houver URLs, desiste

        random.shuffle(available_urls)

        # Prioridade: Tenta primeiro as URLs que NÃO estão na blacklist
        # Se todas estiverem na blacklist, tentamos a primeira disponível mesmo assim (fallback de emergência)
        urls_to_try = available_urls if available_urls else urls
        
        for url in urls_to_try:
            try:
                async with session.post(url, json=payload, timeout=REQUEST_TIMEOUT) as res:
                    if res.status == 200:
                        data = await res.json()
                        if 'result' in data: 
                            if url in rpc_blacklist: del rpc_blacklist[url]
                            if cache_key: balance_cache[cache_key] = (data, time.time())
                            return data
                    elif res.status == 429:
                        logger.warning(f"RPC {url} com limite excedido (429).")
                        rpc_blacklist[url] = time.time()
                        # Não espera aqui, tenta a próxima URL da lista imediatamente
                        continue 
                    else:
                        logger.warning(f"RPC {url} erro {res.status}.")
                        rpc_blacklist[url] = time.time()
            except Exception as e:
                logger.warning(f"Erro na conexão com {url}: {e}")
                rpc_blacklist[url] = time.time()
            except asyncio.TimeoutError:
                logger.warning(f"Timeout ao conectar com RPC {url} para {method}. Adicionando à blacklist temporária.")
                rpc_blacklist[url] = time.time()
            except aiohttp.ClientError as e:
                logger.warning(f"Erro de conexão com RPC {url} para {method}: {e}. Adicionando à blacklist temporária.")
                rpc_blacklist[url] = time.time()
            except json.JSONDecodeError:
                logger.warning(f"Erro ao decodificar JSON do RPC {url} para {method}. Adicionando à blacklist temporária.")
                rpc_blacklist[url] = time.time()
            except Exception as e:
                logger.error(f"Erro inesperado no RPC {url} para {method}: {e}. Adicionando à blacklist temporária.")
                rpc_blacklist[url] = time.time()
        return None

async def get_universal_addresses(seed_phrase):
    try:
        seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
    except Exception: return []
    
    addr_map = []
    seen_addresses = set()
    for account_idx in range(MAX_ACCOUNTS):
        for address_idx in range(GAP_LIMIT):
            # BTC (BIP-44, BIP-49, BIP-84)
            try:
                for coin_type, coin_label in [(Bip84, "Native"), (Bip49, "P2SH-SegWit"), (Bip44, "P2PKH")]:
                    addr = coin_type.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()
                    if addr not in seen_addresses:
                        addr_map.append(("BTC", coin_label, addr))
                        seen_addresses.add(addr)
            except Exception: pass

            # EVM (ETH, BSC, POLYGON) - BIP-44
            try:
                eth_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()
                if eth_addr not in seen_addresses:
                    addr_map.append(("EVM", "ADDR", eth_addr))
                    seen_addresses.add(eth_addr)
            except Exception: pass

            # Solana (BIP-44)
            try:
                sol_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()
                if sol_addr not in seen_addresses:
                    addr_map.append(("SOL", "ADDR", sol_addr))
                    seen_addresses.add(sol_addr)
            except Exception: pass

            # Tron (Múltiplos Caminhos)
            try:
                # 1. Padrão BIP-44 (m/44'/195'/0'/0/0)
                trx_addr_std = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()
                if trx_addr_std not in seen_addresses:
                    addr_map.append(("TRX", "STD", trx_addr_std))
                    seen_addresses.add(trx_addr_std)
                
                # 2. Alternativo (m/44'/195'/0'/0) - Comum em algumas carteiras
                bip32_ctx = Bip32Utils.FromSeed(seed_bytes).DerivePath(f"m/44'/195'/{account_idx}'/0")
                trx_addr_alt = Bip44.FromPublicKey(bip32_ctx.PublicKey().Raw().ToBytes(), Bip44Coins.TRON).PublicKey().ToAddress()
                if trx_addr_alt not in seen_addresses:
                    addr_map.append(("TRX", "ALT", trx_addr_alt))
                    seen_addresses.add(trx_addr_alt)
                
                # 3. Trust Wallet Style (Tron usando caminho de ETH: m/44'/60'/0'/0/index)
                eth_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx)
                trx_addr_trust = Bip44.FromPublicKey(eth_ctx.PublicKey().Raw().ToBytes(), Bip44Coins.TRON).PublicKey().ToAddress()
                if trx_addr_trust not in seen_addresses:
                    addr_map.append(("TRX", "TRUST", trx_addr_trust))
                    seen_addresses.add(trx_addr_trust)
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

async def check_evm_full(session, addr, target_net=None):
    results = []
    networks = [target_net] if target_net else ["ETH", "BSC", "POLYGON", "ARBITRUM", "OPTIMISM", "AVALANCHE", "FANTOM"]
    
    for net in networks:
        urls = RPC_URLS.get(net)
        if not urls: continue
        
        data = await _rpc_call(session, urls, "eth_getBalance", [addr, "latest"])
        if data and 'result' in data:
            try:
                bal = int(data['result'], 16) / 10**18
                if bal > 0: results.append((net, addr, bal))
            except: pass
        
        contract = USDT_CONTRACTS.get(net)
        if contract:
            try:
                call_data = "0x70a08231" + addr[2:].zfill(64)
                t_data = await _rpc_call(session, urls, "eth_call", [{"to": contract, "data": call_data}, "latest"])
                if t_data and 'result' in t_data and t_data['result'] != '0x':
                    t_bal = int(t_data['result'], 16) / 10**6
                    if t_bal > 0: results.append((f"USDT_{net}", addr, t_bal))
            except: pass
    return results

async def check_solana(session, addr):
    results = []
    sol_urls = RPC_URLS["SOL"]

    # Check SOL balance
    sol_balance_data = await _rpc_call(session, sol_urls, "getBalance", [addr])
    if sol_balance_data and 'result' in sol_balance_data:
        sol_balance = sol_balance_data['result']['value'] / 10**9  # Lamports to SOL
        if sol_balance > 0: results.append(("SOL", addr, sol_balance))

    # Check SPL tokens
    spl_tokens_data = await _rpc_call(session, sol_urls, "getTokenAccountsByOwner", [
        addr,
        {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
        {"encoding": "jsonParsed"}
    ])
    if spl_tokens_data and 'result' in spl_tokens_data:
        for token_account in spl_tokens_data['result']['value']:
            try:
                info = token_account['account']['data']['parsed']['info']
                mint = info['mint']
                token_balance = int(info['tokenAmount']['amount']) / (10**int(info['tokenAmount']['decimals']))
                if token_balance > 0: results.append((f"SPL_{mint}", addr, token_balance))
            except Exception as e:
                logger.warning(f"Erro ao processar token SPL para {addr}: {e}")
    return results

async def check_trx(session, addr):
    async with semaphore:
        results = []
        # Tenta Alchemy Tron, TronGrid e se falhar (429), tenta a API pública da Tron
        apis = [
            f"https://tron-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8/v1/accounts/{addr}",
            f"https://api.trongrid.io/v1/accounts/{addr}",
            f"https://api.tronstack.io/v1/accounts/{addr}"
        ]
        for api_url in apis:
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

# ── CEX INTEGRATIONS ──────────────────────────────────────────────────────────

async def check_kraken(session, api_key, api_secret):
    if not api_key or not api_secret: return []
    url = "https://api.kraken.com/0/private/Balance"
    nonce = str(int(time.time() * 1000))
    postdata = f"nonce={nonce}"
    path = "/0/private/Balance"
    encoded = (nonce + postdata).encode()
    message = path.encode() + hashlib.sha256(encoded).digest()
    signature = hmac.new(base64.b64decode(api_secret), message, hashlib.sha512)
    sigdigest = base64.b64encode(signature.digest()).decode()
    headers = {"API-Key": api_key, "API-Sign": sigdigest}
    try:
        async with session.post(url, data=postdata, headers=headers, timeout=REQUEST_TIMEOUT) as res:
            if res.status == 200:
                data = await res.json()
                if not data.get("error"):
                    return [("KRAKEN", asset, float(bal)) for asset, bal in data["result"].items() if float(bal) > 0]
    except Exception: pass
    return []

async def check_kucoin(session, api_key, api_secret, api_passphrase):
    if not api_key or not api_secret: return []
    url = "https://api.kucoin.com/api/v1/accounts"
    now = str(int(time.time() * 1000))
    str_to_sign = now + "GET" + "/api/v1/accounts"
    signature = hmac.new(api_secret.encode(), str_to_sign.encode(), hashlib.sha256)
    sig = base64.b64encode(signature.digest()).decode()
    headers = {"KC-API-KEY": api_key, "KC-API-SIGN": sig, "KC-API-TIMESTAMP": now, "KC-API-PASSPHRASE": api_passphrase, "KC-API-KEY-VERSION": "2"}
    try:
        async with session.get(url, headers=headers, timeout=REQUEST_TIMEOUT) as res:
            if res.status == 200:
                data = await res.json()
                if data.get("code") == "200000":
                    return [("KUCOIN", acc["currency"], float(acc["balance"])) for acc in data["data"] if float(acc["balance"]) > 0]
    except Exception: pass
    return []

async def check_bitfinex(session, api_key, api_secret):
    if not api_key or not api_secret: return []
    url = "https://api-pub.bitfinex.com/v2/auth/r/wallets"
    nonce = str(int(time.time() * 1000))
    auth_payload = f"/api/v2/auth/r/wallets{nonce}"
    signature = hmac.new(api_secret.encode(), auth_payload.encode(), hashlib.sha384).hexdigest()
    headers = {"bfx-nonce": nonce, "bfx-apikey": api_key, "bfx-signature": signature}
    try:
        async with session.post(url, headers=headers, timeout=REQUEST_TIMEOUT) as res:
            if res.status == 200:
                data = await res.json()
                return [("BITFINEX", w[1], float(w[2])) for w in data if float(w[2]) > 0]
    except Exception: pass
    return []

# ── MAIN ORCHESTRATOR ────────────────────────────────────────────────────────

async def check_balance_all(seed):
    seed = seed.strip()
    if not seed: return None
    
    # Se for uma API Key (formato key:secret ou similar), trata como CEX
    if ":" in seed and len(seed) > 30:
        parts = seed.split(":")
        async with aiohttp.ClientSession() as session:
            if len(parts) == 2: # Kraken ou Bitfinex
                res = await asyncio.gather(check_kraken(session, parts[0], parts[1]), check_bitfinex(session, parts[0], parts[1]))
            elif len(parts) == 3: # KuCoin (Key:Secret:Passphrase)
                res = [await check_kucoin(session, parts[0], parts[1], parts[2])]
            else: res = []
            found = [item for sublist in res for item in sublist]
            return (seed, found) if found else None

    addr_map = await get_universal_addresses(seed)
    if not addr_map: return None

    async with aiohttp.ClientSession() as session:
        tasks = []
        for coin, label, addr in addr_map:
            if coin == "BTC": tasks.append(check_btc(session, addr))
            elif coin == "EVM": tasks.append(check_evm_full(session, addr))
            elif coin == "TRX": tasks.append(check_trx(session, addr))
            elif coin == "SOL": tasks.append(check_solana(session, addr))
        
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
