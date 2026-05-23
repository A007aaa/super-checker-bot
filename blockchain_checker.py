import asyncio
import aiohttp
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins, Bip84, Bip84Coins, Bip39MnemonicValidator
)

REQUEST_TIMEOUT = 20
MAX_CONCURRENT_REQUESTS = 10
DERIVATION_PATHS = 10

semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def _rpc_call(session, url, method, params):
    async with semaphore:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            async with session.post(url, json=payload, timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200:
                    return await res.json()
        except:
            pass
        return None

async def get_all_addresses(seed_phrase):
    """Gera todos os endereços possíveis a partir de uma seed phrase"""
    try:
        if not Bip39MnemonicValidator().IsValid(seed_phrase.strip()):
            return []
        
        seed_bytes = Bip39SeedGenerator(seed_phrase.strip()).Generate()
        addresses = []
        
        for i in range(DERIVATION_PATHS):
            try:
                addresses.append(("BTC-Legacy", Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except:
                pass
            
            try:
                addresses.append(("BTC-SegWit", Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except:
                pass
            
            try:
                addresses.append(("BTC-Native", Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except:
                pass
            
            try:
                eth_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()
                addresses.append(("ETH", eth_addr))
            except:
                pass
            
            try:
                addresses.append(("TRX", Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except:
                pass
        
        return addresses
    except:
        return []

async def check_btc(session, addr):
    try:
        async with session.get(f"https://blockchain.info/balance?active={addr}", timeout=REQUEST_TIMEOUT) as res:
            if res.status == 200:
                data = await res.json()
                bal = data.get(addr, {}).get("final_balance", 0) / 10**8
                if bal > 0:
                    return ("BTC", addr, bal)
    except:
        pass
    return None

async def check_eth(session, addr):
    url = "https://cloudflare-eth.com/"
    data = await _rpc_call(session, url, "eth_getBalance", [addr, "latest"])
    if data and 'result' in data:
        try:
            bal = int(data['result'], 16) / 10**18
            if bal > 0:
                return ("ETH", addr, bal)
        except:
            pass
    return None

async def check_bsc(session, addr):
    url = "https://bsc-dataseed.binance.org/"
    data = await _rpc_call(session, url, "eth_getBalance", [addr, "latest"])
    if data and 'result' in data:
        try:
            bal = int(data['result'], 16) / 10**18
            if bal > 0:
                return ("BNB", addr, bal)
        except:
            pass
    return None

async def check_polygon(session, addr):
    url = "https://polygon-rpc.com/"
    data = await _rpc_call(session, url, "eth_getBalance", [addr, "latest"])
    if data and 'result' in data:
        try:
            bal = int(data['result'], 16) / 10**18
            if bal > 0:
                return ("MATIC", addr, bal)
        except:
            pass
    return None

async def check_trx(session, addr):
    try:
        async with session.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=REQUEST_TIMEOUT) as res:
            if res.status == 200:
                data = await res.json()
                if data.get('data'):
                    acc = data['data'][0]
                    bal = acc.get('balance', 0) / 10**6
                    if bal > 0:
                        return ("TRX", addr, bal)
    except:
        pass
    return None

async def check_seed_balance(seed_phrase):
    """Verifica saldo em todos os endereços gerados a partir da seed"""
    addresses = await get_all_addresses(seed_phrase)
    
    if not addresses:
        return None
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for coin_type, addr in addresses:
            if coin_type.startswith("BTC"):
                tasks.append(check_btc(session, addr))
            elif coin_type == "ETH":
                tasks.append(check_eth(session, addr))
                tasks.append(check_bsc(session, addr))
                tasks.append(check_polygon(session, addr))
            elif coin_type == "TRX":
                tasks.append(check_trx(session, addr))
        
        try:
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=120)
        except:
            results = []
    
    balances = []
    for result in results:
        if result and not isinstance(result, Exception):
            balances.append(result)
    
    if balances:
        return (seed_phrase, balances)
    return None
