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

async def check_sol(session, addr):
    async with semaphore:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
        data = await fetch_post(session, SOL_RPC_URLS, payload)
        if data and 'result' in data:
            bal = data['result'].get('value', 0) / 10**9
            if bal > 0:
                return ("SOL", addr, bal)
    return None

async def check_eth_usdt(session, addr):
    async with semaphore:
        # ETH Balance
        payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [addr, "latest"]}
        data = await fetch_post(session, ETH_RPC_URLS, payload)
        if data and 'result' in data:
            bal = int(data['result'], 16) / 10**18
            if bal > 0:
                return ("ETH", addr, bal)

        # USDT (ERC20)
        usdt_contract = "0xdac17f958d2ee523a2206206994597c13d831ec7"
        data_call = "0x70a08231" + addr[2:].lower().zfill(64)
        payload_u = {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": usdt_contract, "data": data_call}, "latest"]}
        data_u = await fetch_post(session, ETH_RPC_URLS, payload_u)
        if data_u and 'result' in data_u:
            u_bal = int(data_u['result'], 16) / 10**6
            if u_bal > 0:
                return ("USDT_ETH", addr, u_bal)
    return None

async def check_btc(session, addr):
    async with semaphore:
        try:
            # Usando a API do Blockchain.info ou similar
            async with session.get(f"https://blockchain.info/q/addressbalance/{addr}", timeout=10) as res:
                if res.status == 200:
                    bal = int(await res.text()) / 10**8
                    if bal > 0:
                        return ("BTC", addr, bal)
        except:
            pass
    return None

async def check_tron_usdt(session, addr):
    async with semaphore:
        try:
            async with session.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=10) as res:
                if res.status == 200:
                    data = await res.json()
                    if data.get('data'):
                        acc = data['data'][0]
                        trx_bal = acc.get('balance', 0) / 10**6
                        if trx_bal > 0:
                            return ("TRX", addr, trx_bal)
                        
                        trc20_list = acc.get('trc20', [])
                        for token_data in trc20_list:
                            # O formato da API do Trongrid para TRC20 pode variar
                            for contract, balance in token_data.items():
                                if contract == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t':
                                    u_bal = float(balance) / 10**6
                                    if u_bal > 0:
                                        return ("USDT_TRX", addr, u_bal)
        except:
            pass
    return None

async def check_balance_master(type, value):
    async with aiohttp.ClientSession() as session:
        tasks = []
        if type == "SEED":
            try:
                seed_bytes = Bip39SeedGenerator(value).Generate()
                
                # Verificando os primeiros 5 endereços para cada padrão comum
                for i in range(5):
                    # BTC Native Segwit (BIP84) - bc1...
                    bip84_mst = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN)
                    addr_btc = bip84_mst.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()
                    tasks.append(check_btc(session, addr_btc))
                    
                    # ETH (BIP44) - 0x...
                    bip44_eth = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM)
                    addr_eth = bip44_eth.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()
                    tasks.append(check_eth_usdt(session, addr_eth))
                    
                    # SOL (BIP44)
                    bip44_sol = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)
                    addr_sol = bip44_sol.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()
                    tasks.append(check_sol(session, addr_sol))

                    # TRON (BIP44)
                    bip44_trx = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON)
                    addr_trx = bip44_trx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress()
                    tasks.append(check_tron_usdt(session, addr_trx))
                
            except Exception as e:
                logger.error(f"Erro ao derivar seed: {e}")
                return None
        else:
            # Se for chave privada direta
            addr = value
            if addr.startswith('0x'):
                tasks.append(check_eth_usdt(session, addr))
            elif addr.startswith('T'):
                tasks.append(check_tron_usdt(session, addr))
            elif addr.startswith('1') or addr.startswith('3') or addr.startswith('bc1'):
                tasks.append(check_btc(session, addr))
            else:
                tasks.append(check_sol(session, addr))

        results = await asyncio.gather(*tasks)
        found = [r for r in results if r]
        if found:
            # Remover duplicatas de resultados (mesmo saldo/endereço detectado múltiplas vezes)
            unique_found = []
            seen = set()
            for r in found:
                key = f"{r[0]}:{r[1]}"
                if key not in seen:
                    unique_found.append(r)
                    seen.add(key)
            return (value, unique_found)
    return None
