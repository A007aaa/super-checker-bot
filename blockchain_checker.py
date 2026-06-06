import asyncio
import aiohttp
import logging
from mnemonic import Mnemonic
from eth_account import Account

# Habilitar recursos de HD Wallet para eth-account
Account.enable_unaudited_hdwallet_features()

logger = logging.getLogger(__name__)

# Configurações de Performance Ultra-Agressiva
REQUEST_TIMEOUT = 5.0 
MAX_CONCURRENT_BATCHES = 50 
BATCH_SIZE = 10 # Quantas seeds verificar em um único pedido HTTP
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

RPC_URLS = {
    "BSC": ["https://bnb-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8", "https://bsc-dataseed.binance.org/"],
    "POLYGON": ["https://polygon-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8", "https://polygon-rpc.com/"],
    "ETH": ["https://eth-mainnet.g.alchemy.com/v2/tTv5fdlUEgRX7S6mFtkF8", "https://cloudflare-eth.com/"]
}

semaphore = asyncio.Semaphore(MAX_CONCURRENT_BATCHES)

async def check_batch(session, seeds_batch):
    """Verifica um lote de seeds em todas as redes usando Batching JSON-RPC"""
    async with semaphore:
        results = []
        # Preparar endereços e mapeamento
        addr_to_seed = {}
        for seed in seeds_batch:
            try:
                acc = Account.from_mnemonic(seed)
                addr_to_seed[acc.address] = seed
            except: continue
        
        if not addr_to_seed: return []

        addresses = list(addr_to_seed.keys())
        
        # Para cada rede, enviar um lote (batch)
        for net, urls in RPC_URLS.items():
            # Criar o payload de lote
            batch_payload = []
            for idx, addr in enumerate(addresses):
                batch_payload.append({
                    "jsonrpc": "2.0",
                    "id": idx,
                    "method": "eth_getBalance",
                    "params": [addr, "latest"]
                })
            
            for url in urls:
                try:
                    async with session.post(url, json=batch_payload, timeout=REQUEST_TIMEOUT) as res:
                        if res.status == 200:
                            responses = await res.json()
                            if isinstance(responses, list):
                                for resp in responses:
                                    idx = resp.get("id")
                                    result = resp.get("result")
                                    if result and idx is not None:
                                        bal = int(result, 16) / 10**18
                                        if bal > 0.000001:
                                            addr = addresses[idx]
                                            results.append((addr_to_seed[addr], net, addr, bal))
                            break # Sucesso nesta rede, pula para próxima
                except:
                    continue
        return results

async def process_all_seeds(seeds):
    """Processa todas as seeds em lotes de alta velocidade"""
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        all_found = []
        tasks = []
        
        # Dividir em lotes para Batching
        for i in range(0, len(seeds), BATCH_SIZE):
            batch = seeds[i:i + BATCH_SIZE]
            tasks.append(check_batch(session, batch))
        
        # Executar todos os lotes em paralelo
        batch_results = await asyncio.gather(*tasks)
        
        # Organizar resultados
        final_results = {}
        for batch_res in batch_results:
            for seed, net, addr, bal in batch_res:
                if seed not in final_results:
                    final_results[seed] = []
                final_results[seed].append((net, addr, bal))
        
        return final_results
