import asyncio
import aiohttp
import logging
from mnemonic import Mnemonic
from eth_account import Account

# Habilitar recursos de HD Wallet para eth-account
Account.enable_unaudited_hdwallet_features()

logger = logging.getLogger(__name__)

# Configurações de Performance Ultra-Agressiva
REQUEST_TIMEOUT = 3.0 # Timeout de 3 segundos para não travar
MAX_CONCURRENT_REQUESTS = 100 # Aumentado para 100x
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

RPC_URLS = {
    "BSC": ["https://bnb-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8", "https://bsc-dataseed.binance.org/"],
    "POLYGON": ["https://polygon-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8", "https://polygon-rpc.com/"],
    "ETH": ["https://eth-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8", "https://cloudflare-eth.com/"]
}

semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def _rpc_call(session, urls, method, params):
    async with semaphore:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        for url in urls:
            try:
                async with session.post(url, json=payload, timeout=REQUEST_TIMEOUT) as res:
                    if res.status == 200:
                        data = await res.json()
                        if 'result' in data: return data
            except: continue
        return None

async def check_balance_all(seed_phrase):
    try:
        # Gerar endereço de forma instantânea
        acc = Account.from_mnemonic(seed_phrase)
        addr = acc.address
        
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            results = []
            # Verificar todas as redes em paralelo real para cada seed
            tasks = []
            networks = ["ETH", "BSC", "POLYGON"]
            for net in networks:
                urls = RPC_URLS.get(net)
                tasks.append(_rpc_call(session, urls, "eth_getBalance", [addr, "latest"]))
            
            responses = await asyncio.gather(*tasks)
            
            for i, data in enumerate(responses):
                if data and 'result' in data:
                    try:
                        bal = int(data['result'], 16) / 10**18
                        if bal > 0.000001: # Ignorar poeira irrelevante
                            results.append((networks[i], addr, bal))
                    except: pass
            
            if results:
                return seed_phrase, results
    except:
        pass
    return None
