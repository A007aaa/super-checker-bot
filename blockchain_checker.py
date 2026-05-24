import asyncio
import aiohttp
import logging
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip84, Bip84Coins, Bip49, Bip49Coins
)

logger = logging.getLogger(__name__)
semaphore = asyncio.Semaphore(50)

# Lista de nós RPC públicos para maior confiabilidade
ETH_RPC_URLS = [
    "https://cloudflare-eth.com/",
    "https://eth.llamarpc.com",
    "https://rpc.ankr.com/eth"
]

SOL_RPC_URLS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-mainnet.rpc.extrnode.com",
    "https://rpc.ankr.com/solana"
]

async def fetch_post(session, urls, payload):
    for url in urls:
        try:
            async with session.post(url, json=payload, timeout=10) as res:
                if res.status == 200:
                    return await res.json()
        except:
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
        # USDT: Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8En2XPyH
        # USDC: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
        payload_tokens = {
            "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
            "params": [addr, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding": "jsonParsed"}]
        }
        data_tokens = await fetch_post(session, SOL_RPC_URLS, payload_tokens)
        if data_tokens and 'result' in data_tokens and 'value' in data_tokens['result']:
            for account in data_tokens['result']['value']:
                info = account['account']['data']['parsed']['info']
                mint = info['mint']
                amount = float(info['tokenAmount']['uiAmount'])
                if amount > 0:
                    if mint == "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8En2XPyH":
                        results.append(("USDT_SOL", addr, amount))
                    elif mint == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":
                        results.append(("USDC_SOL", addr, amount))
        return results

async def check_eth_assets(session, addr):
    async with semaphore:
        results = []
        # ETH Balance
        payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [addr, "latest"]}
        data = await fetch_post(session, ETH_RPC_URLS, payload)
        if data and 'result' in data:
            bal = int(data['result'], 16) / 10**18
            if bal > 0:
                results.append(("ETH", addr, bal))

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
        try:
            async with session.get(f"https://blockchain.info/q/addressbalance/{addr}", timeout=10) as res:
                if res.status == 200:
                    bal = int(await res.text()) / 10**8
                    if bal > 0:
                        return [("BTC", addr, bal)]
        except: pass
    return []

async def check_tron_assets(session, addr):
    async with semaphore:
        results = []
        try:
            # TRX & TRC20
            async with session.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=10) as res:
                if res.status == 200:
                    data = await res.json()
                    if data.get('success') and data.get('data'):
                        acc = data['data'][0]
                        # TRX
                        trx_bal = acc.get('balance', 0) / 10**6
                        if trx_bal > 0:
                            results.append(("TRX", addr, trx_bal))
                        
                        # TRC20 Tokens
                        trc20_list = acc.get('trc20', [])
                        for token in trc20_list:
                            for contract, balance in token.items():
                                if contract == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t": # USDT
                                    u_bal = int(balance) / 10**6
                                    if u_bal > 0: results.append(("USDT_TRC20", addr, u_bal))
                                elif contract == "TEkxiTeY4Bf3Y89S4V2pEwKX8N8m1ogq5B": # USDC (Example contract)
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
                # FORÇA BRUTA: 50 endereços por seed
                for i in range(50):
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

        all_results = await asyncio.gather(*tasks)
        # Flatten the list of lists
        found = [item for sublist in all_results for item in sublist]
        
        if found:
            unique_found = []
            seen = set()
            for r in found:
                key = f"{r[0]}:{r[1]}"
                if key not in seen:
                    unique_found.append(r)
                    seen.add(key)
            return (value, unique_found)
    return None
