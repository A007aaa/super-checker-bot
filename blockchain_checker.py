import requests
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins, Bip84, Bip84Coins, Bip39MnemonicValidator
)

def get_addresses(seed_phrase):
    """Gera endereços para múltiplas blockchains usando BIP44/BIP49/BIP84."""
    try:
        seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
        addresses = {}

        # Bitcoin (3 formatos)
        try:
            btc_bip44 = Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['BTC_Legacy'] = btc_bip44.PublicKey().ToAddress()
            
            btc_bip49 = Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['BTC_SegWit'] = btc_bip49.PublicKey().ToAddress()
            
            btc_bip84 = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['BTC_Native'] = btc_bip84.PublicKey().ToAddress()
        except:
            pass

        # Ethereum (compatível com EVM chains)
        try:
            eth = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            eth_addr = eth.PublicKey().ToAddress()
            addresses['ETH'] = eth_addr
            addresses['BSC'] = eth_addr
            addresses['AVAX'] = eth_addr
            addresses['MATIC'] = eth_addr
            addresses['ARB'] = eth_addr
            addresses['OP'] = eth_addr
            addresses['BASE'] = eth_addr
            addresses['ZKSYNC'] = eth_addr
            addresses['LINEA'] = eth_addr
        except:
            pass

        # Tron
        try:
            trx = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['TRX'] = trx.PublicKey().ToAddress()
        except:
            pass

        # Solana
        try:
            sol = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['SOL'] = sol.PublicKey().ToAddress()
        except:
            pass

        # Litecoin
        try:
            ltc = Bip44.FromSeed(seed_bytes, Bip44Coins.LITECOIN).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['LTC'] = ltc.PublicKey().ToAddress()
        except:
            pass

        # Cardano
        try:
            ada = Bip44.FromSeed(seed_bytes, Bip44Coins.CARDANO).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['ADA'] = ada.PublicKey().ToAddress()
        except:
            pass

        # Cosmos
        try:
            atom = Bip44.FromSeed(seed_bytes, Bip44Coins.COSMOS).Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            addresses['ATOM'] = atom.PublicKey().ToAddress()
        except:
            pass

        return addresses
    except:
        return {}

def check_balance_all(seed):
    """Verifica saldos em múltiplas blockchains."""
    seed = seed.strip()
    if not seed:
        return None
    
    try:
        if not Bip39MnemonicValidator().IsValid(seed):
            return None
    except:
        return None
        
    addresses = get_addresses(seed)
    if not addresses:
        return None
    
    found = []
    
    # Bitcoin
    for btc_type in ['BTC_Legacy', 'BTC_SegWit', 'BTC_Native']:
        if btc_type in addresses:
            try:
                addr = addresses[btc_type]
                res = requests.get(f"https://blockchain.info/balance?active={addr}", timeout=5).json()
                bal = res.get(addr, {}).get("final_balance", 0) / 10**8
                if bal > 0:
                    found.append((btc_type, addr, bal))
            except:
                pass
    
    # Ethereum e EVM chains
    if 'ETH' in addresses:
        eth_addr = addresses['ETH']
        
        try:
            res = requests.get(f"https://api.blockcypher.com/v1/eth/main/addrs/{eth_addr}/balance", timeout=5).json()
            bal = res.get("balance", 0) / 10**18
            if bal > 0:
                found.append(("ETH", eth_addr, bal))
        except:
            pass
        
        # USDT ERC20
        try:
            res = requests.get(f"https://api.ethplorer.io/getAddressInfo/{eth_addr}?apiKey=freekey", timeout=5).json()
            if 'tokens' in res:
                for t in res['tokens']:
                    if t['tokenInfo']['symbol'] == 'USDT':
                        bal = float(t['balance']) / (10**int(t['tokenInfo']['decimals']))
                        if bal > 0:
                            found.append(("USDT_ERC20", eth_addr, bal))
        except:
            pass
    
    # Tron e USDT TRC20
    if 'TRX' in addresses:
        trx_addr = addresses['TRX']
        try:
            res = requests.get(f"https://api.trongrid.io/v1/accounts/{trx_addr}", timeout=5).json()
            if res.get('data'):
                bal = res['data'][0].get('balance', 0) / 10**6
                if bal > 0:
                    found.append(("TRX", trx_addr, bal))
                
                trc20_balances = res['data'][0].get('trc20', [])
                for token in trc20_balances:
                    if 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' in token:
                        bal = float(token['TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t']) / 10**6
                        if bal > 0:
                            found.append(("USDT_TRC20", trx_addr, bal))
        except:
            pass
    
    # Solana
    if 'SOL' in addresses:
        sol_addr = addresses['SOL']
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [sol_addr]}
            res = requests.post("https://api.mainnet-beta.solana.com", json=payload, timeout=5).json()
            bal = res.get('result', {}).get('value', 0) / 10**9
            if bal > 0:
                found.append(("SOL", sol_addr, bal))
        except:
            pass

    if found:
        return (seed, found)
    return None
