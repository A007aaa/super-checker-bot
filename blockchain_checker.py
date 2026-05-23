import asyncio
import aiohttp
from typing import Optional, Tuple, List

REQUEST_TIMEOUT = 20
MAX_CONCURRENT_REQUESTS = 5

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

async def check_btc(session, addr: str) -> Optional[Tuple[str, float]]:
    try:
        async with session.get(f"https://blockchain.info/balance?active={addr}", timeout=REQUEST_TIMEOUT) as res:
            if res.status == 200:
                data = await res.json()
                bal = data.get(addr, {}).get("final_balance", 0) / 10**8
                if bal > 0:
                    return ("BTC", bal)
    except:
        pass
    return None

async def check_eth(session, addr: str) -> Optional[Tuple[str, float]]:
    url = "https://cloudflare-eth.com/"
    data = await _rpc_call(session, url, "eth_getBalance", [addr, "latest"])
    if data and 'result' in data:
        try:
            bal = int(data['result'], 16) / 10**18
            if bal > 0:
                return ("ETH", bal)
        except:
            pass
    return None

async def check_bsc(session, addr: str) -> Optional[Tuple[str, float]]:
    url = "https://bsc-dataseed.binance.org/"
    data = await _rpc_call(session, url, "eth_getBalance", [addr, "latest"])
    if data and 'result' in data:
        try:
            bal = int(data['result'], 16) / 10**18
            if bal > 0:
                return ("BNB", bal)
        except:
            pass
    return None

async def check_polygon(session, addr: str) -> Optional[Tuple[str, float]]:
    url = "https://polygon-rpc.com/"
    data = await _rpc_call(session, url, "eth_getBalance", [addr, "latest"])
    if data and 'result' in data:
        try:
            bal = int(data['result'], 16) / 10**18
            if bal > 0:
                return ("MATIC", bal)
        except:
            pass
    return None

async def check_trx(session, addr: str) -> Optional[Tuple[str, float]]:
    try:
        async with session.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=REQUEST_TIMEOUT) as res:
            if res.status == 200:
                data = await res.json()
                if data.get('data'):
                    acc = data['data'][0]
                    bal = acc.get('balance', 0) / 10**6
                    if bal > 0:
                        return ("TRX", bal)
    except:
        pass
    return None

async def check_wallet_balance(address: str) -> Optional[Tuple[str, List[Tuple[str, float]]]]:
    address = address.strip()
    if not address:
        return None
    
    async with aiohttp.ClientSession() as session:
        tasks = [
            check_btc(session, address),
            check_eth(session, address),
            check_bsc(session, address),
            check_polygon(session, address),
            check_trx(session, address),
        ]
        
        try:
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=60)
        except:
            results = []
    
    balances = []
    for result in results:
        if result and not isinstance(result, Exception):
            balances.append(result)
    
    if balances:
        return (address, balances)
    return None
