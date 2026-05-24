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

# ── Hyper Turbo Tunables ────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 10          # Aumentado para acomodar RPCs mais lentos, especialmente para Tron
SEED_TIMEOUT      = 120         # Aumentado para suportar varredura exaustiva sem interrupções
MAX_CONCURRENT_REQUESTS = 10    # Aumentado levemente para maior velocidade, mantendo segurança contra 429
CHECK_INDEX_COUNT = 1           # Foco total no endereço #0 (Velocidade Máxima)
GAP_LIMIT = 10                  # Aumentado para maior assertividade, especialmente para Tron
MAX_ACCOUNTS = 3                # Aumentado para maior assertividade
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

RPC_URLS = {
    "BSC": ["https://bsc-dataseed.binance.org/"],
    "POLYGON": ["https://polygon-rpc.com/"],
    "ETH": ["https://cloudflare-eth.com/"]
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
        random.shuffle(urls) # Rotacionar URLs para distribuir a carga e tentar diferentes endpoints
        for url in urls:
            try:
                async with session.post(url, json=payload, timeout=REQUEST_TIMEOUT) as res:
                    if res.status == 200:
                        data = await res.json()
                        if 'result' in data: return data
                    else:
                        logger.warning(f"RPC {url} retornou status {res.status} para {method} com params {params}")
            except aiohttp.ClientError as e:
                logger.warning(f"Erro de conexão com RPC {url} para {method} com params {params}: {e}")
            except asyncio.TimeoutError:
                logger.warning(f"Timeout ao conectar com RPC {url} para {method} com params {params}")
            except json.JSONDecodeError:
                logger.warning(f"Erro ao decodificar JSON do RPC {url} para {method} com params {params}")
            except Exception as e:
                logger.error(f"Erro inesperado no RPC {url} para {method} com params {params}: {e}")
        return None

async def get_universal_addresses(seed_phrase):
    seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
    addr_map = []

    for account_idx in range(MAX_ACCOUNTS):
        for address_idx in range(GAP_LIMIT):
            # BTC (BIP-44, BIP-49, BIP-84)
            try:
                # BIP-84 (Native SegWit)
                addr_map.append(("BTC", "Native", Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()))
                # BIP-49 (P2SH-SegWit)
                addr_map.append(("BTC", "P2SH-SegWit", Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()))
                # BIP-44 (P2PKH Legacy)
                addr_map.append(("BTC", "P2PKH", Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx).PublicKey().ToAddress()))
            except Exception: pass

            # EVM (BIP-44)
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
                # Usando Bip32 diretamente para caminhos customizados
                bip32_ctx = Bip32Utils.FromSeed(seed_bytes).DerivePath(f"m/44'/195'/{account_idx}'/0")
                trx_addr_alt = Bip44.FromPublicKey(bip32_ctx.PublicKey().Raw().ToBytes(), Bip44Coins.TRON).PublicKey().ToAddress()
                addr_map.append(("TRX", "ALT", trx_addr_alt))
                
                # 3. Trust Wallet Style (Tron usando caminho de ETH: m/44'/60'/0'/0/index)
                # Algumas carteiras multi-chain usam a chave de ETH para derivar Tron
                eth_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(account_idx).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_idx)
                trx_addr_trust = Bip44.FromPublicKey(eth_ctx.PublicKey().Raw().ToBytes(), Bip44Coins.TRON).PublicKey().ToAddress()
                addr_map.append(("TRX", "TRUST", trx_addr_trust))
            except Exception: pass

    return addr_map

async def check_btc(session, addr):
    async with semaphore:
        try:
            async with session.get(f"https://blockchain.info/balance?active={addr}", timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200:
                    data = await res.json()
                    bal = data.get(addr, {}).get("final_balance", 0) / 10**8
                    if bal > 0: return ("BTC", addr, bal)
        except Exception as e:
            logger.warning(f"Erro ao verificar BTC para {addr}: {e}")
        return None

async def check_evm_full(session, addr):
    results = []
    for net, urls in RPC_URLS.items():
        data = await _rpc_call(session, urls, "eth_getBalance", [addr, "latest"])
        if data and 'result' in data:
            bal = int(data['result'], 16) / 10**18
            if bal > 0.0001: results.append((net, addr, bal))
        
        contract = USDT_CONTRACTS.get(net)
        if contract:
            call_data = "0x70a08231" + addr[2:].zfill(64)
            t_data = await _rpc_call(session, urls, "eth_call", [{"to": contract, "data": call_data}, "latest"])
            if t_data and 'result' in t_data and t_data['result'] != '0x':
                t_bal = int(t_data['result'], 16) / 10**6
                if t_bal > 0.1: results.append((f"USDT_{net}", addr, t_bal))
    return results

async def check_trx(session, addr):
    async with semaphore:
        results = []
        try:
            # TronGrid V1 API é excelente para ver saldo de TRX e TRC20 em uma única chamada
            # Adicionando um pequeno delay aleatório para evitar picos de requisição
            await asyncio.sleep(random.uniform(0.5, 2.0))
            async with session.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200:
                    data = await res.json()
                    if data.get('data') and len(data['data']) > 0:
                        acc = data['data'][0]
                        
                        # 1. Verificar saldo de TRX
                        bal_trx = acc.get('balance', 0) / 10**6
                        if bal_trx > 0.01: # Filtro mínimo de TRX
                            results.append(("TRX", addr, bal_trx))
                        
                        # 2. Verificar tokens TRC20 (incluindo USDT)
                        trc20_list = acc.get('trc20', [])
                        for token_data in trc20_list:
                            for contract, val in token_data.items():
                                try:
                                    token_bal = float(val) / 10**6 # A maioria dos TRC20 usa 6 decimais como o USDT
                                    if token_bal > 0.01:
                                        symbol = "USDT" if contract == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' else "TRC20"
                                        results.append((symbol, addr, token_bal))
                                except: continue
                else:
                    logger.warning(f"TronGrid retornou status {res.status} para {addr}")
        except Exception as e:
            logger.warning(f"Erro ao verificar TRX/TRC20 para {addr}: {e}")
        return results

async def check_balance_all(seed):
    seed = seed.strip()
    if not seed or not Bip39MnemonicValidator().IsValid(seed): return None
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
        except asyncio.TimeoutError:
            logger.warning(f"Timeout geral ao verificar seed {seed}")
            raw = []
        except Exception as e:
            logger.error(f"Erro inesperado ao verificar seed {seed}: {e}")
            raw = []

    found = []
    for item in raw:
        if item and not isinstance(item, Exception):
            if isinstance(item, list): found.extend(item)
            else: found.append(item)
    
    # Remover duplicatas de resultados (mesmo endereço em caminhos diferentes)
    unique_found = []
    seen_results = set()
    for coin, addr, bal in found:
        key = (coin, addr)
        if key not in seen_results:
            unique_found.append((coin, addr, bal))
            seen_results.add(key)
            
    return (seed, unique_found) if unique_found else None
