import asyncio
import aiohttp
import logging
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip84, Bip84Coins, SolAddr, AdaShelleyAddr
)

logger = logging.getLogger(__name__)

# Configurações de Conexão
MAX_CONCURRENT = 50
semaphore = asyncio.Semaphore(MAX_CONCURRENT)

async def check_sol(session, addr):
    async with semaphore:
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
            async with session.post("https://api.mainnet-beta.solana.com", json=payload, timeout=8) as res:
                if res.status == 200:
                    data = await res.json()
                    bal = data.get('result', {}).get('value', 0) / 10**9
                    if bal > 0: return ("SOL", addr, bal)
        except: pass
    return None

async def check_eth_usdt(session, addr):
    async with semaphore:
        try:
            # ETH Balance
            payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [addr, "latest"]}
            async with session.post("https://cloudflare-eth.com/", json=payload, timeout=8) as res:
                if res.status == 200:
                    data = await res.json()
                    eth_bal = int(data.get('result', '0x0'), 16) / 10**18
                    if eth_bal > 0: return ("ETH", addr, eth_bal)
            
            # USDT (ERC20)
            usdt_contract = "0xdac17f958d2ee523a2206206994597c13d831ec7"
            data_call = "0x70a08231" + addr[2:].zfill(64)
            payload_usdt = {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": usdt_contract, "data": data_call}, "latest"]}
            async with session.post("https://cloudflare-eth.com/", json=payload_usdt, timeout=8) as res:
                if res.status == 200:
                    data = await res.json()
                    usdt_bal = int(data.get('result', '0x0'), 16) / 10**6
                    if usdt_bal > 0: return ("USDT_ETH", addr, usdt_bal)
        except: pass
    return None

async def check_btc(session, addr):
    async with semaphore:
        try:
            async with session.get(f"https://blockchain.info/q/addressbalance/{addr}", timeout=8) as res:
                if res.status == 200:
                    bal = int(await res.text()) / 10**8
                    if bal > 0: return ("BTC", addr, bal)
        except: pass
    return None

async def check_tron_usdt(session, addr):
    async with semaphore:
        try:
            async with session.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=8) as res:
                if res.status == 200:
                    data = await res.json()
                    if data.get('data'):
                        acc = data['data'][0]
                        # TRX
                        trx_bal = acc.get('balance', 0) / 10**6
                        if trx_bal > 0: return ("TRX", addr, trx_bal)
                        # USDT (TRC20)
                        for token in acc.get('trc20', []):
                            if 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' in token:
                                usdt_bal = float(token['TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t']) / 10**6
                                if usdt_bal > 0: return ("USDT_TRX", addr, usdt_bal)
        except: pass
    return None

async def check_ada(session, addr):
    async with semaphore:
        try:
            # Usando Blockfrost ou API pública similar se disponível, ou mock para estrutura
            # Para ADA, geralmente precisamos de uma API key, mas vamos tentar um explorer público
            async with session.get(f"https://cardano-mainnet.blockfrost.io/api/v0/addresses/{addr}", headers={"project_id": "public"}, timeout=8) as res:
                if res.status == 200:
                    data = await res.json()
                    bal = int(data.get('amount', [{}])[0].get('quantity', 0)) / 10**6
                    if bal > 0: return ("ADA", addr, bal)
        except: pass
    return None

async def check_balance_all(seed):
    try:
        seed_bytes = Bip39SeedGenerator(seed).Generate()
        tasks = []
        async with aiohttp.ClientSession() as session:
            # BTC Native SegWit
            btc_addr = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
            tasks.append(check_btc(session, btc_addr))
            
            # ETH / USDT ERC20
            eth_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
            tasks.append(check_eth_usdt(session, eth_addr))
            
            # SOL
            sol_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            sol_addr = SolAddr.Encode(sol_ctx.PublicKey().Raw().ToBytes())
            tasks.append(check_sol(session, sol_addr))
            
            # TRX / USDT TRC20
            trx_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
            tasks.append(check_tron_usdt(session, trx_addr))
            
            # ADA
            ada_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.CARDANO_SHELLEY).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            ada_addr = AdaShelleyAddr.Encode(ada_ctx.PublicKey().Raw().ToBytes())
            tasks.append(check_ada(session, ada_addr))

            results = await asyncio.gather(*tasks)
            found = [r for r in results if r]
            return (seed, found) if found else None
    except: return None
