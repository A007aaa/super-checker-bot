import asyncio
import aiohttp
import logging
import random
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins, Bip84, Bip84Coins, SolAddr
)

logger = logging.getLogger(__name__)

# Configurações Turbo
MAX_CONCURRENT = 100
semaphore = asyncio.Semaphore(MAX_CONCURRENT)

async def check_solana(session, addr):
    async with semaphore:
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
            async with session.post("https://api.mainnet-beta.solana.com", json=payload, timeout=5) as res:
                if res.status == 200:
                    data = await res.json()
                    bal = data.get('result', {}).get('value', 0) / 10**9
                    if bal > 0: return ("SOL", addr, bal)
        except: pass
        return None

async def check_evm(session, addr):
    # Focar em BSC e ETH para velocidade
    urls = ["https://bsc-dataseed.binance.org/", "https://cloudflare-eth.com/"]
    async with semaphore:
        for url in urls:
            try:
                payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [addr, "latest"]}
                async with session.post(url, json=payload, timeout=5) as res:
                    if res.status == 200:
                        data = await res.json()
                        bal = int(data.get('result', '0x0'), 16) / 10**18
                        if bal > 0: return ("EVM", addr, bal)
            except: continue
    return None

async def check_balance_all(seed):
    try:
        seed_bytes = Bip39SeedGenerator(seed).Generate()
        addrs = []
        
        # Solana - Caminho padrão (m/44'/501'/0'/0')
        sol_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
        addrs.append(("SOL", SolAddr.Encode(sol_ctx.PublicKey().Raw().ToBytes())))
        
        # EVM - Caminho padrão
        eth_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
        addrs.append(("EVM", eth_addr))
        
        # BTC Native SegWit
        btc_addr = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
        addrs.append(("BTC", btc_addr))

        async with aiohttp.ClientSession() as session:
            tasks = []
            for coin, addr in addrs:
                if coin == "SOL": tasks.append(check_solana(session, addr))
                elif coin == "EVM": tasks.append(check_evm(session, addr))
                elif coin == "BTC": 
                    # Simples check para BTC
                    async with session.get(f"https://blockchain.info/q/addressbalance/{addr}", timeout=5) as r:
                        if r.status == 200:
                            b = int(await r.text()) / 10**8
                            if b > 0: tasks.append(asyncio.sleep(0, result=("BTC", addr, b)))

            results = await asyncio.gather(*tasks)
            found = [r for r in results if r]
            return (seed, found) if found else None
    except:
        return None
