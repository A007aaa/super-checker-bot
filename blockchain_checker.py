import asyncio
import aiohttp
import logging
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip84, Bip84Coins, Bip49, Bip49Coins, SolAddr, EthAddr
)
import base58

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
                    if bal > 0: return ("SOL", addr, bal)
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
                    if bal > 0: return ("ETH", addr, bal)
            
            # USDT (ERC20)
            usdt_contract = "0xdac17f958d2ee523a2206206994597c13d831ec7"
            data_call = "0x70a08231" + addr[2:].lower().zfill(64)
            payload_u = {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": usdt_contract, "data": data_call}, "latest"]}
            async with session.post("https://cloudflare-eth.com/", json=payload_u, timeout=8) as res:
                if res.status == 200:
                    data = await res.json()
                    u_bal = int(data.get('result', '0x0'), 16) / 10**6
                    if u_bal > 0: return ("USDT_ETH", addr, u_bal)
        except Exception as e:
            logger.debug(f"Erro ETH/USDT ({addr}): {e}")
    return None

async def check_btc(session, addr):
    async with semaphore:
        try:
            async with session.get(f"https://blockchain.info/q/addressbalance/{addr}", timeout=8) as res:
                if res.status == 200:
                    bal = int(await res.text()) / 10**8
                    if bal > 0: return ("BTC", addr, bal)
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
                        if trx_bal > 0: return ("TRX", addr, trx_bal)
                        for token in acc.get('trc20', []):
                            if 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' in token:
                                u_bal = float(token['TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t']) / 10**6
                                if u_bal > 0: return ("USDT_TRX", addr, u_bal)
        except Exception as e:
            logger.debug(f"Erro TRON ({addr}): {e}")
    return None

async def check_balance_master(type, value):
    async with aiohttp.ClientSession() as session:
        tasks = []
        if type == "SEED":
            try:
                seed_bytes = Bip39SeedGenerator(value).Generate()
                
                # 1. SOLANA (Caminhos Comuns)
                for path in [0, 1, 2]:
                    sol_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(path).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
                    tasks.append(check_sol(session, SolAddr.Encode(sol_ctx.PublicKey().Raw().ToBytes())))
                
                # 2. ETHEREUM (Múltiplas Contas)
                for acc in range(3):
                    eth_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(acc).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
                    tasks.append(check_eth_usdt(session, eth_addr))
                
                # 3. BITCOIN (SegWit, SegWit Híbrido e Legacy)
                # Bip84 (Native SegWit - bc1...)
                tasks.append(check_btc(session, Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()))
                # Bip49 (SegWit Híbrido - 3...)
                tasks.append(check_btc(session, Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()))
                # Bip44 (Legacy - 1...)
                tasks.append(check_btc(session, Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()))
                
                # 4. TRON
                trx_addr = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
                tasks.append(check_tron_usdt(session, trx_addr))
                
            except Exception as e:
                logger.error(f"Erro ao derivar endereços da SEED: {e}")
        
        elif type == "SOL_KEY":
            try:
                decoded = base58.b58decode(value)
                if len(decoded) == 64:
                    addr = SolAddr.Encode(decoded[32:])
                    tasks.append(check_sol(session, addr))
            except Exception as e:
                logger.error(f"Erro ao processar SOL_KEY: {e}")
            
        elif type == "ETH_KEY":
            try:
                # Se for hex de 64 chars, derivar endereço ETH
                from eth_keys import keys
                priv_key = keys.PrivateKey(bytes.fromhex(value.replace('0x', '')))
                addr = priv_key.public_key.to_checksum_address()
                tasks.append(check_eth_usdt(session, addr))
            except ImportError:
                logger.warning("Biblioteca eth-keys não instalada para derivar ETH_KEY")
            except Exception as e:
                logger.error(f"Erro ao processar ETH_KEY: {e}")

        if not tasks:
            return None

        results = await asyncio.gather(*tasks)
        found = [r for r in results if r]
        return (value, found) if found else None
