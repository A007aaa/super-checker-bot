import asyncio
import aiohttp
import logging
import random
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip84, Bip84Coins, Bip49, Bip49Coins
)

logger = logging.getLogger(__name__)
# Reduzindo o semáforo para evitar bloqueios agressivos
semaphore = asyncio.Semaphore(10)

# Lista de nós RPC públicos ampliada para rotação
ETH_RPC_URLS = [
    "https://cloudflare-eth.com/",
    "https://eth.llamarpc.com",
    "https://rpc.ankr.com/eth",
    "https://ethereum.publicnode.com",
    "https://1rpc.io/eth"
]

SOL_RPC_URLS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-mainnet.rpc.extrnode.com",
    "https://rpc.ankr.com/solana",
    "https://api.metaplex.solana.com",
    "https://solana.publicnode.com"
]

async def fetch_post(session, urls, payload, retries=3):
    # Embaralha as URLs para não usar sempre a mesma e ser bloqueado
    random.shuffle(urls)
    for url in urls:
        for attempt in range(retries):
            try:
                async with session.post(url, json=payload, timeout=15) as res:
                    if res.status == 200:
                        return await res.json()
                    elif res.status == 429: # Rate Limit
                        await asyncio.sleep(2 ** attempt) # Backoff exponencial
                        continue
            except:
                await asyncio.sleep(1)
                continue
    return None

async def check_sol_assets(session, addr):
    async with semaphore:
        results = []
        # SOL Balance
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
        data = await fetch_post(session, SOL_RPC_URLS, payload)
        if data and 'result' in data and data['result'] is not None:
            val = data['result'].get('value', 0)
            if val and val > 0:
                results.append(("SOL", addr, val / 10**9))

        # SPL Tokens (USDT & USDC)
        payload_tokens = {
            "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
            "params": [addr, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding": "jsonParsed"}]
        }
        data_tokens = await fetch_post(session, SOL_RPC_URLS, payload_tokens)
        if data_tokens and 'result' in data_tokens and 'value' in data_tokens['result']:
            for account in data_tokens['result']['value']:
                try:
                    info = account['account']['data']['parsed']['info']
                    mint = info['mint']
                    amount = float(info['tokenAmount']['uiAmount'])
                    if amount > 0:
                        if mint == "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8En2XPyH":
                            results.append(("USDT_SOL", addr, amount))
                        elif mint == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":
                            results.append(("USDC_SOL", addr, amount))
                except: continue
        return results

async def check_eth_assets(session, addr):
    async with semaphore:
        results = []
        # ETH Balance
        payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [addr, "latest"]}
        data = await fetch_post(session, ETH_RPC_URLS, payload)
        if data and 'result' in data:
            try:
                bal = int(data['result'], 16) / 10**18
                if bal > 0:
                    results.append(("ETH", addr, bal))
            except: pass

        # ERC20 Tokens
        tokens = {
            "USDT_ETH": ("0xdac17f958d2ee523a2206206994597c13d831ec7", 6),
            "USDC_ETH": ("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", 6)
        }
        for name, (contract, decimals) in tokens.items():
            data_call = "0x70a08231" + addr[2:].lower().zfill(64)
            payload_u = {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": contract, "data": data_call}, "latest"]}
            data_u = await fetch_post(session, ETH_RPC_URLS, payload_u)
            if data_u and 'result' in data_u and data_u['result'] != '0x':
                try:
                    u_bal = int(data_u['result'], 16) / 10**decimals
                    if u_bal > 0:
                        results.append((name, addr, u_bal))
                except: continue
        return results

async def check_btc(session, addr):
    async with semaphore:
        for attempt in range(3):
            try:
                # Alternando entre Blockchain.info e BlockCypher para evitar limites
                url = f"https://blockchain.info/q/addressbalance/{addr}" if attempt % 2 == 0 else f"https://api.blockcypher.com/v1/btc/main/addrs/{addr}/balance"
                async with session.get(url, timeout=15) as res:
                    if res.status == 200:
                        data = await res.json() if "blockcypher" in url else await res.text()
                        bal = (data.get('balance', 0) if isinstance(data, dict) else int(data)) / 10**8
                        if bal > 0:
                            return [("BTC", addr, bal)]
                        return []
                    elif res.status == 429:
                        await asyncio.sleep(2)
            except:
                await asyncio.sleep(1)
        return []

async def check_tron_assets(session, addr):
    async with semaphore:
        results = []
        try:
            async with session.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=15) as res:
                if res.status == 200:
                    data = await res.json()
                    if data.get('success') and data.get('data'):
                        acc = data['data'][0]
                        trx_bal = acc.get('balance', 0) / 10**6
                        if trx_bal > 0:
                            results.append(("TRX", addr, trx_bal))
                        trc20_list = acc.get('trc20', [])
                        for token in trc20_list:
                            for contract, balance in token.items():
                                if contract == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t": # USDT
                                    u_bal = int(balance) / 10**6
                                    if u_bal > 0: results.append(("USDT_TRC20", addr, u_bal))
                                elif contract == "TEkxiTeY4Bf3Y89S4V2pEwKX8N8m1ogq5B": # USDC
                                    u_bal = int(balance) / 10**6
                                    if u_bal > 0: results.append(("USDC_TRC20", addr, u_bal))
        except: pass
    return results

async def check_balance_master(type, value):
    async with aiohttp.ClientSession() as session:
        tasks = []
        if type == "SEED":
            try:
                seed_bytes = Bip39SeedGenerator(value).Generate()
                # Reduzindo para 20 endereços por vez para evitar banimento por IP, mas com maior qualidade de verificação
                for i in range(20):
                    # BTC (BIP84, BIP44)
                    for coin_type in [Bip84Coins.BITCOIN, Bip44Coins.BITCOIN]:
                        try:
                            mst = Bip84.FromSeed(seed_bytes, coin_type) if coin_type == Bip84Coins.BITCOIN else Bip44.FromSeed(seed_bytes, coin_type)
                            addr = mst.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()
                            tasks.append(check_btc(session, addr))
                        except: continue
                    
                    # ETH
                    bip44_eth = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM)
                    addr_eth = bip44_eth.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()
                    tasks.append(check_eth_assets(session, addr_eth))
                    
                    # SOL
                    bip44_sol = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)
                    addr_sol = bip44_sol.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()
                    tasks.append(check_sol_assets(session, addr_sol))
                    
                    # SOL ALT
                    try:
                        addr_sol_alt = bip44_sol.Purpose().Coin().Account(i).PublicKey().ToAddress()
                        tasks.append(check_sol_assets(session, addr_sol_alt))
                    except: pass

                    # TRON
                    bip44_trx = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON)
                    addr_trx = bip44_trx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()
                    tasks.append(check_tron_assets(session, addr_trx))
                
            except Exception as e:
                logger.error(f"Erro ao derivar seed: {e}")
                return None
        else:
            addr = value
            if addr.startswith('0x'):
                tasks.append(check_eth_assets(session, addr))
            elif addr.startswith('T'):
                tasks.append(check_tron_assets(session, addr))
            elif addr.startswith('1') or addr.startswith('3') or addr.startswith('bc1'):
                tasks.append(check_btc(session, addr))
            else:
                tasks.append(check_sol_assets(session, addr))

        # Executa em lotes menores para não sobrecarregar
        all_results = []
        for i in range(0, len(tasks), 5):
            batch = tasks[i:i+5]
            batch_results = await asyncio.gather(*batch)
            for br in batch_results:
                if br: all_results.extend(br)
            await asyncio.sleep(0.5) # Pausa entre lotes
            
        if all_results:
            unique_found = []
            seen = set()
            for r in all_results:
                key = f"{r[0]}:{r[1]}"
                if key not in seen:
                    unique_found.append(r)
                    seen.add(key)
            return (value, unique_found)
    return None
