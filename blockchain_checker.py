import asyncio
import aiohttp
import logging
import random
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip84, Bip84Coins, Bip49, Bip49Coins
)

logger = logging.getLogger(__name__)
# Semáforo para controle de concorrência
semaphore = asyncio.Semaphore(50)

# Lista de RPCs com a sua chave da Alchemy e alternativas
ETH_RPC_URLS = [
    "https://eth-mainnet.g.alchemy.com/v2/o9ITDgWvucfpVAJDLJ_Lb",
    "https://cloudflare-eth.com/",
    "https://eth.llamarpc.com",
    "https://rpc.ankr.com/eth"
]

# Adicionando suporte a BSC e Polygon para encontrar saldos em outras redes EVM
BSC_RPC_URLS = ["https://binance.llamarpc.com", "https://bsc-dataseed.binance.org/"]
POLYGON_RPC_URLS = ["https://polygon.llamarpc.com", "https://polygon-rpc.com"]

SOL_RPC_URLS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-mainnet.rpc.extrnode.com",
    "https://rpc.ankr.com/solana"
]

async def fetch_post(session, urls, payload, retries=5):
    random.shuffle(urls)
    for attempt in range(retries):
        url = urls[attempt % len(urls)]
        try:
            async with session.post(url, json=payload, timeout=10) as res:
                if res.status == 200:
                    data = await res.json()
                    if data and 'result' in data:
                        return data
                elif res.status == 429:
                    await asyncio.sleep(1.5 * (attempt + 1))
        except:
            await asyncio.sleep(0.5)
    return None

async def check_evm_assets(session, addr, rpc_urls, network_name):
    async with semaphore:
        results = []
        # Native Balance (ETH/BNB/MATIC)
        payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [addr, "latest"]}
        data = await fetch_post(session, rpc_urls, payload)
        if data and 'result' in data:
            try:
                bal = int(data['result'], 16) / 10**18
                if bal > 0.000001: # Ignora saldos irrelevantes de poeira
                    results.append((network_name, addr, bal))
            except: pass

        # USDT/USDC em redes EVM
        tokens = {
            f"USDT_{network_name}": "0xdac17f958d2ee523a2206206994597c13d831ec7" if network_name == "ETH" else "0x55d398326f99059ff775485246999027b3197955",
            f"USDC_{network_name}": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48" if network_name == "ETH" else "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"
        }
        for name, contract in tokens.items():
            data_call = "0x70a08231" + addr[2:].lower().zfill(64)
            payload_u = {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": contract, "data": data_call}, "latest"]}
            data_u = await fetch_post(session, rpc_urls, payload_u)
            if data_u and 'result' in data_u and data_u['result'] != '0x':
                try:
                    u_bal = int(data_u['result'], 16) / 10**6 # USDT/USDC geralmente 6 casas
                    if u_bal > 0.1:
                        results.append((name, addr, u_bal))
                except: pass
        return results

async def check_sol_assets(session, addr):
    async with semaphore:
        results = []
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
        data = await fetch_post(session, SOL_RPC_URLS, payload)
        if data and 'result' in data:
            val = data['result'].get('value', 0) / 10**9
            if val > 0: results.append(("SOL", addr, val))

        # Tokens Solana
        payload_t = {"jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner", "params": [addr, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding": "jsonParsed"}]}
        data_t = await fetch_post(session, SOL_RPC_URLS, payload_t)
        if data_t and 'result' in data_t and 'value' in data_t['result']:
            for acc in data_t['result']['value']:
                try:
                    info = acc['account']['data']['parsed']['info']
                    amt = float(info['tokenAmount']['uiAmount'])
                    if amt > 0.1:
                        results.append((f"TOKEN_SOL_{info['mint'][:4]}", addr, amt))
                except: continue
        return results

async def check_btc(session, addr):
    async with semaphore:
        # Tenta Blockstream (mais confiável para bc1) e Blockchain.info
        try:
            async with session.get(f"https://blockstream.info/api/address/{addr}", timeout=10) as res:
                if res.status == 200:
                    d = await res.json()
                    bal = (d['chain_stats']['funded_txo_sum'] - d['chain_stats']['spent_txo_sum']) / 10**8
                    if bal > 0: return [("BTC", addr, bal)]
        except: pass
        try:
            async with session.get(f"https://blockchain.info/q/addressbalance/{addr}", timeout=10) as res:
                if res.status == 200:
                    bal = int(await res.text()) / 10**8
                    if bal > 0: return [("BTC", addr, bal)]
        except: pass
        return []

async def check_tron_assets(session, addr):
    async with semaphore:
        results = []
        try:
            async with session.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=10) as res:
                if res.status == 200:
                    d = await res.json()
                    if d.get('success') and d.get('data'):
                        acc = d['data'][0]
                        bal = acc.get('balance', 0) / 10**6
                        if bal > 0: results.append(("TRX", addr, bal))
                        for token in acc.get('trc20', []):
                            for contract, balance in token.items():
                                amt = int(balance) / 10**6
                                if amt > 0.1: results.append(("USDT_TRC20", addr, amt))
        except: pass
    return results

async def check_balance_master(type, value):
    async with aiohttp.ClientSession() as session:
        tasks = []
        if type == "SEED":
            try:
                seed_bytes = Bip39SeedGenerator(value).Generate()
                # Verificação profunda: 15 endereços por padrão (Equilíbrio entre velocidade e cobertura)
                for i in range(15):
                    # BTC: Native Segwit, Segwit, Legacy
                    tasks.append(check_btc(session, Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                    tasks.append(check_btc(session, Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                    tasks.append(check_btc(session, Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                    
                    # EVM: ETH, BSC, Polygon
                    addr_evm = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()
                    tasks.append(check_evm_assets(session, addr_evm, ETH_RPC_URLS, "ETH"))
                    tasks.append(check_evm_assets(session, addr_evm, BSC_RPC_URLS, "BSC"))
                    tasks.append(check_evm_assets(session, addr_evm, POLYGON_RPC_URLS, "POLYGON"))
                    
                    # SOL: Standard e Trust Wallet path
                    bip44_sol = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)
                    tasks.append(check_sol_assets(session, bip44_sol.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
                    try: tasks.append(check_sol_assets(session, bip44_sol.Purpose().Coin().Account(i).PublicKey().ToAddress()))
                    except: pass

                    # TRON
                    tasks.append(check_tron_assets(session, Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()))
            except Exception as e:
                logger.error(f"Erro na derivação: {e}")
                return None
        else:
            # Lógica para Chave Privada Direta
            addr = value # (Simplificado para o master processar)
            tasks.append(check_evm_assets(session, addr, ETH_RPC_URLS, "ETH"))
            tasks.append(check_sol_assets(session, addr))

        batch_results = await asyncio.gather(*tasks)
        all_results = [item for sublist in batch_results for item in sublist if sublist]
            
        if all_results:
            unique = []
            seen = set()
            for r in all_results:
                if f"{r[0]}:{r[1]}" not in seen:
                    unique.append(r)
                    seen.add(f"{r[0]}:{r[1]}")
            return (value, unique)
    return None
