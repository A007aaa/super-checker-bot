import asyncio
import aiohttp
import logging
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip84, Bip84Coins, Bip49, Bip49Coins
)

logger = logging.getLogger(__name__)
semaphore = asyncio.Semaphore(50)

async def check_sol(session, addr):
    async with semaphore:
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]}
            async with session.post("https://api.mainnet-beta.solana.com", json=payload, timeout=8) as res:
                if res.status == 200:
                    data = await res.json()
                    bal = data.get('result', {}).get('value', 0) / 10**9
                    if bal > 0:
                        return ("SOL", addr, bal)
        except Exception as e:
            logger.debug(f"Erro SOL ({addr}): {e}")
    return None

async def check_eth_usdt(session, addr):
    async with semaphore:
        try:
            # ETH
            payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [addr, "latest"]}
            async with session.post("https://cloudflare-eth.com/", json=payload, timeout=8) as res:
                if res.status == 200:
                    data = await res.json()
                    bal = int(data.get('result', '0x0'), 16) / 10**18
                    if bal > 0:
                        return ("ETH", addr, bal)

            # USDT (ERC20)
            usdt_contract = "0xdac17f958d2ee523a2206206994597c13d831ec7"
            data_call = "0x70a08231" + addr[2:].lower().zfill(64)
            payload_u = {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": usdt_contract, "data": data_call}, "latest"]}
            async with session.post("https://cloudflare-eth.com/", json=payload_u, timeout=8) as res:
                if res.status == 200:
                    data = await res.json()
                    u_bal = int(data.get('result', '0x0'), 16) / 10**6
                    if u_bal > 0:
                        return ("USDT_ETH", addr, u_bal)
        except Exception as e:
            logger.debug(f"Erro ETH/USDT ({addr}): {e}")
    return None

async def check_btc(session, addr):
    async with semaphore:
        try:
            async with session.get(f"https://blockchain.info/q/addressbalance/{addr}", timeout=8) as res:
                if res.status == 200:
                    bal = int(await res.text()) / 10**8
                    if bal > 0:
                        return ("BTC", addr, bal)
        except Exception as e:
            logger.debug(f"Erro BTC ({addr}): {e}")
    return None

async def check_tron_usdt(session, addr):
    async with semaphore:
        try:
            async with session.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=8) as res:
                if res.status == 200:
                    data = await res.json()
                    if data.get('data'):
                        acc = data['data'][0]
                        trx_bal = acc.get('balance', 0) / 10**6
                        if trx_bal > 0:
                            return ("TRX", addr, trx_bal)
                        
                        trc20_list = acc.get('trc20', [])
                        for token in trc20_list:
                            if 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' in token:
                                u_bal = float(token['TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t']) / 10**6
                                if u_bal > 0:
                                    return ("USDT_TRX", addr, u_bal)
        except Exception as e:
            logger.debug(f"Erro TRON ({addr}): {e}")
    return None

async def check_balance_master(type, value):
    async with aiohttp.ClientSession() as session:
        addresses = []
        if type == "SEED":
            try:
                seed_bytes = Bip39SeedGenerator(value).Generate()
                
                # BTC Segwit (BIP84)
                bip84_mst = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN)
                # Correção: Bip84PublicKey não tem .Raw, usar .ToAddress() diretamente do objeto de endereço
                addresses.append(bip84_mst.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress())
                
                # ETH (BIP44)
                bip44_mst = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM)
                addresses.append(bip44_mst.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress())
                
                # SOL
                sol_mst = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)
                addresses.append(sol_mst.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress())
                
                # TRX
                trx_mst = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON)
                addresses.append(trx_mst.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress())
                
            except Exception as e:
                logger.error(f"Erro ao derivar seed: {e}")
                return None
        else:
            addresses.append(value)

        tasks = []
        for addr in addresses:
            if not isinstance(addr, str): continue
            
            if addr.startswith('1') or addr.startswith('3') or addr.startswith('bc1'):
                tasks.append(check_btc(session, addr))
            elif addr.startswith('0x'):
                tasks.append(check_eth_usdt(session, addr))
            elif addr.startswith('T'):
                tasks.append(check_tron_usdt(session, addr))
            else:
                tasks.append(check_sol(session, addr))

        results = await asyncio.gather(*tasks)
        found = [r for r in results if r]
        if found:
            return (value, found)
    return None
