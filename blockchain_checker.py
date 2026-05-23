import asyncio
import aiohttp
import json
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins, Bip84, Bip84Coins, Bip39MnemonicValidator
)

# ── Tunables ────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 20          
SEED_TIMEOUT      = 240         
MAX_RETRIES       = 2           
CHECK_INDEX_COUNT = 5           
MAX_CONCURRENT_REQUESTS = 5     
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

# RPCs e APIs de Tokens
RPC_URLS = {
    "BSC": "https://bsc-dataseed.binance.org/",
    "POLYGON": "https://polygon-rpc.com/",
    "ETH": "https://cloudflare-eth.com/"
}

# Contratos Comuns de USDT
USDT_CONTRACTS = {
    "ETH": "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "BSC": "0x55d398326f99059ff775485246999027b3197955",
    "POLYGON": "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"
}
# ────────────────────────────────────────────────────────────────────────────

semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def _rpc_call(session, url, method, params):
    async with semaphore:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            async with session.post(url, json=payload, timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200: return await res.json()
        except: pass
        return None

async def get_universal_addresses(seed_phrase):
    try:
        seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
        addr_map = []
        for i in range(CHECK_INDEX_COUNT):
            # BTC (Legacy, SegWit, Native)
            try:
                addr_map.append(("BTC", f"Legacy_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("BTC", f"SegWit_#{i}", Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                addr_map.append(("BTC", f"Native_#{i}", Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except: pass
            # EVM (Padrão MetaMask/Trust)
            try:
                eth_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()
                addr_map.append(("EVM", f"ADDR_#{i}", eth_addr))
            except: pass
            # Tron
            try:
                addr_map.append(("TRX", f"TRX_#{i}", Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except: pass
        return addr_map
    except: return []

async def check_btc(session, label, addr):
    try:
        async with session.get(f"https://blockchain.info/balance?active={addr}", timeout=REQUEST_TIMEOUT) as res:
            if res.status == 200:
                data = await res.json()
                bal = data.get(addr, {}).get("final_balance", 0) / 10**8
                if bal > 0: return (f"BTC ({label})", addr, bal)
    except: pass
    return None

async def check_evm_full(session, label, addr):
    results = []
    for net, url in RPC_URLS.items():
        # 1. Saldo Nativo (ETH, BNB, MATIC)
        data = await _rpc_call(session, url, "eth_getBalance", [addr, "latest"])
        if data and 'result' in data:
            bal = int(data['result'], 16) / 10**18
            if bal > 0.0001: results.append((f"{net} ({label})", addr, bal))
        
        # 2. Saldo USDT (Chamada direta ao contrato)
        contract = USDT_CONTRACTS.get(net)
        if contract:
            # data: 0x70a08231 + endereço sem 0x preenchido com zeros até 64 caracteres
            call_data = "0x70a08231" + addr[2:].zfill(64)
            t_data = await _rpc_call(session, url, "eth_call", [{"to": contract, "data": call_data}, "latest"])
            if t_data and 'result' in t_data and t_data['result'] != '0x':
                t_bal = int(t_data['result'], 16) / 10**6 if net != "ETH" else int(t_data['result'], 16) / 10**6
                if t_bal > 0.1: results.append((f"USDT_{net} ({label})", addr, t_bal))
    
    # 3. Outros Tokens via Ethplorer (Apenas ETH)
    try:
        async with session.get(f"https://api.ethplorer.io/getAddressInfo/{addr}?apiKey=freekey", timeout=10) as res:
            if res.status == 200:
                data_t = await res.json()
                if 'tokens' in data_t:
                    for t in data_t['tokens']:
                        bal = float(t['balance']) / (10 ** int(t['tokenInfo']['decimals']))
                        if bal > 0.01: results.append((f"TOKEN_{t['tokenInfo']['symbol']} ({label})", addr, bal))
    except: pass
    return results

async def check_trx(session, label, addr):
    try:
        async with session.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=REQUEST_TIMEOUT) as res:
            if res.status == 200:
                data = await res.json()
                if data.get('data'):
                    acc = data['data'][0]
                    bal = acc.get('balance', 0) / 10**6
                    if bal > 0: return [(f"TRX ({label})", addr, bal)]
                    
                    found_tokens = []
                    for t in acc.get('trc20', []):
                        for contract, val in t.items():
                            if float(val) > 0:
                                symbol = "USDT" if contract == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' else "TRC20"
                                found_tokens.append((f"{symbol} ({label})", addr, float(val)/10**6))
                    return found_tokens
    except: pass
    return []

async def check_balance_all(seed):
    seed = seed.strip()
    if not seed or not Bip39MnemonicValidator().IsValid(seed): return None
    addr_map = await get_universal_addresses(seed)
    if not addr_map: return None

    async with aiohttp.ClientSession() as session:
        tasks = []
        for coin, label, addr in addr_map:
            if coin == "BTC": tasks.append(check_btc(session, label, addr))
            elif coin == "EVM": tasks.append(check_evm_full(session, label, addr))
            elif coin == "TRX": tasks.append(check_trx(session, label, addr))
        
        try:
            raw = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=SEED_TIMEOUT)
        except: raw = []

    found = []
    for item in raw:
        if item and not isinstance(item, Exception):
            if isinstance(item, list): found.extend(item)
            else: found.append(item)
    return (seed, found) if found else None
