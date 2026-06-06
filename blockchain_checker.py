import asyncio
import aiohttp
import logging
from eth_account import Account

# Habilitar recursos de HD Wallet para eth-account
Account.enable_unaudited_hdwallet_features()

logger = logging.getLogger(__name__)

# Configurações de Performance Equilibrada (Velocidade + Precisão)
REQUEST_TIMEOUT = 8.0 
MAX_CONCURRENT_TASKS = 50 
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

RPC_URLS = {
    "BSC": ["https://bnb-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8", "https://bsc-dataseed.binance.org/"],
    "POLYGON": ["https://polygon-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8", "https://polygon-rpc.com/"],
    "ETH": ["https://eth-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8", "https://cloudflare-eth.com/"],
    "SOL": ["https://solana-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8", "https://api.mainnet-beta.solana.com/"]
}

semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

async def check_solana(session, addr):
    """Verifica saldo na rede Solana"""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
    for url in RPC_URLS["SOL"]:
        try:
            async with session.post(url, json=payload, timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200:
                    data = await res.json()
                    val = data.get("result", {}).get("value", 0)
                    return val / 10**9
        except: continue
    return 0

async def check_evm(session, addr, network):
    """Verifica saldo em redes EVM"""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [addr, "latest"]}
    for url in RPC_URLS.get(network, []):
        try:
            async with session.post(url, json=payload, timeout=REQUEST_TIMEOUT) as res:
                if res.status == 200:
                    data = await res.json()
                    if 'result' in data:
                        return int(data['result'], 16) / 10**18
        except: continue
    return 0

async def check_single_seed(session, seed):
    """Verifica uma única seed em todas as redes com precisão"""
    async with semaphore:
        results = []
        try:
            # Endereço EVM (ETH, BSC, Polygon)
            acc_evm = Account.from_mnemonic(seed)
            addr_evm = acc_evm.address
            
            # Verificar EVM em paralelo
            evm_tasks = [
                check_evm(session, addr_evm, "ETH"),
                check_evm(session, addr_evm, "BSC"),
                check_evm(session, addr_evm, "POLYGON")
            ]
            
            # Para Solana, precisaríamos de uma lib extra para derivar de mnemonic, 
            # mas vamos focar em EVM por enquanto para garantir que o básico funcione 100%
            
            evm_results = await asyncio.gather(*evm_tasks)
            networks = ["ETH", "BSC", "POLYGON"]
            
            for i, bal in enumerate(evm_results):
                if bal > 0:
                    results.append((networks[i], addr_evm, bal))
                    
        except: pass
        return (seed, results) if results else None

async def process_all_seeds(seeds):
    """Processa todas as seeds com máxima precisão e alta velocidade"""
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tasks = [check_single_seed(session, seed) for seed in seeds]
        batch_results = await asyncio.gather(*tasks)
        
        final_results = {}
        for res in batch_results:
            if res:
                seed, findings = res
                final_results[seed] = findings
        return final_results
