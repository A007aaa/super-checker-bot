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
                    if bal > 0: return (("SOL", addr, bal),)
        except: pass
    return ()

async def check_eth_usdt(session, addr):
    async with semaphore:
        results = []
        try:
            # ETH Balance
            payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [addr, "latest"]}
            async with session.post("https://cloudflare-eth.com/", json=payload, timeout=8) as res:
                if res.status == 200:
                    data = await res.json()
                    bal = int(data.get('result', '0x0'), 16) / 10**18
                    if bal > 0: results.append(("ETH", addr, bal))

            # USDT (ERC20)
            usdt_contract = "0xdac17f958d2ee523a2206206994597c13d831ec7"
            data_call = "0x70a08231" + addr[2:].lower().zfill(64)
            payload_u = {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": usdt_contract, "data": data_call}, "latest"]}
            async with session.post("https://cloudflare-eth.com/", json=payload_u, timeout=8) as res:
                if res.status == 200:
                    data = await res.json()
                    u_bal = int(data.get('result', '0x0'), 16) / 10**6
                    if u_bal > 0: results.append(("USDT_ETH", addr, u_bal))
        except: pass
        return tuple(results)

async def check_btc(session, addr):
    async with semaphore:
        try:
            async with session.get(f"https://blockchain.info/q/addressbalance/{addr}", timeout=8) as res:
                if res.status == 200:
                    bal = int(await res.text()) / 10**8
                    if bal > 0: return (("BTC", addr, bal),)
        except: pass
    return ()

async def check_tron_usdt(session, addr):
    async with semaphore:
        results = []
        try:
            async with session.get(f"https://api.trongrid.io/v1/accounts/{addr}", timeout=8) as res:
                if res.status == 200:
                    data = await res.json()
                    if data.get('data'):
                        acc = data['data'][0]
                        trx_bal = acc.get('balance', 0) / 10**6
                        if trx_bal > 0: results.append(("TRX", addr, trx_bal))
                        trc20_list = acc.get('trc20', [])
                        for token in trc20_list:
                            if 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' in token:
                                u_bal = float(token['TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t']) / 10**6
                                if u_bal > 0: results.append(("USDT_TRX", addr, u_bal))
        except: pass
        return tuple(results)

async def check_balance_master(type, value):
    async with aiohttp.ClientSession() as session:
        addr_map = {} # {addr: (coin_type, check_function)}
        
        if type == "SEED":
            try:
                seed_bytes = Bip39SeedGenerator(value).Generate()
                
                # 1. BTC Native Segwit (bc1...) - BIP84
                b84 = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
                addr_map[b84.PublicKey().ToAddress()] = ("BTC_SEGWIT", check_btc)
                
                # 2. BTC Legacy (1...) - BIP44
                b44_btc = Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
                addr_map[b44_btc.PublicKey().ToAddress()] = ("BTC_LEGACY", check_btc)
                
                # 3. ETH/USDT (0x...) - BIP44
                eth = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
                addr_map[eth.PublicKey().ToAddress()] = ("ETH", check_eth_usdt)
                
                # 4. SOL (Base58) - BIP44
                sol = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
                addr_map[sol.PublicKey().ToAddress()] = ("SOL", check_sol)
                
                # 5. TRX (T...) - BIP44
                trx = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
                addr_map[trx.PublicKey().ToAddress()] = ("TRX", check_tron_usdt)
                
            except Exception as e:
                logger.error(f"Erro derivação: {e}")
                return None
        elif type == "KEY_SOL":
            # Chave privada Solana (Base58) → verificar apenas SOL
            addr_map[value] = ("KEY_SOL", check_sol)

        elif type == "KEY_HEX":
            # Chave privada Ethereum (hex) → verificar apenas ETH e USDT
            addr = value if value.startswith("0x") else f"0x{value}"
            addr_map[addr] = ("KEY_HEX", check_eth_usdt)

        elif type == "ADDR_ETH":
            # Endereço Ethereum direto → verificar ETH e USDT
            addr_map[value] = ("ADDR_ETH", check_eth_usdt)

        elif type == "ADDR_BTC":
            # Endereço Bitcoin direto → verificar BTC
            addr_map[value] = ("ADDR_BTC", check_btc)

        elif type == "ADDR_TRON":
            # Endereço Tron direto → verificar TRX e USDT
            addr_map[value] = ("ADDR_TRON", check_tron_usdt)

        elif type == "ADDR_SOL":
            # Endereço Solana direto → verificar SOL
            addr_map[value] = ("ADDR_SOL", check_sol)

        else:
            # Fallback: detectar pelo prefixo para tipos desconhecidos
            if value.startswith("0x") and len(value) == 42:
                addr_map[value] = ("ADDR_ETH", check_eth_usdt)
            elif value.startswith("T") and len(value) == 34:
                addr_map[value] = ("ADDR_TRON", check_tron_usdt)
            elif value.startswith("bc1") or value.startswith(("1", "3")):
                addr_map[value] = ("ADDR_BTC", check_btc)
            else:
                # Último fallback: tentar como endereço Solana
                addr_map[value] = ("ADDR_SOL", check_sol)

        tasks = []
        for addr, (coin_type, check_func) in addr_map.items():
            tasks.append(check_func(session, addr))

        raw_results = await asyncio.gather(*tasks)
        
        # Achatar resultados (alguns retornam tuplas de tuplas)
        final_found = []
        for r in raw_results:
            if not r: continue
            if isinstance(r, (list, tuple)):
                final_found.extend(r)
            
        if final_found:
            return (value, final_found)
    return None

