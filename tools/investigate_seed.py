import os
import sys
import asyncio
import argparse
from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip84, Bip84Coins
)
from blockchain_checker import check_balance_master


def derive_addresses(seed_phrase: str, scan_addresses: int, scan_accounts: int):
    seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
    derived = {}
    for acct in range(scan_accounts):
        derived[acct] = {}
        for idx in range(scan_addresses):
            try:
                b84 = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(acct).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx)
                btc_sgw = b84.PublicKey().ToAddress()
                b44_btc = Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(acct).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx)
                btc_legacy = b44_btc.PublicKey().ToAddress()
                eth = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(acct).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx)
                eth_addr = eth.PublicKey().ToAddress()
                sol = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(acct).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx)
                sol_addr = sol.PublicKey().ToAddress()
                trx = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(acct).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx)
                trx_addr = trx.PublicKey().ToAddress()

                derived[acct][idx] = {
                    'BTC_SEGWIT': btc_sgw,
                    'BTC_LEGACY': btc_legacy,
                    'ETH': eth_addr,
                    'SOL': sol_addr,
                    'TRX': trx_addr,
                }
            except Exception as e:
                derived[acct][idx] = {'error': str(e)}
    return derived


async def run_check(seed_phrase: str):
    print("Running balance check (this will make network requests using the configured providers)...")
    res = await check_balance_master("SEED", seed_phrase)
    print("\n--- check_balance_master result ---")
    print(res)


def print_derived(derived):
    for acct, idxs in derived.items():
        print(f"\nAccount {acct}:")
        for idx, addrs in idxs.items():
            if 'error' in addrs:
                print(f"  idx {idx}: ERROR deriving - {addrs['error']}")
                continue
            print(f"  idx {idx}: BTC_SGW={addrs['BTC_SEGWIT']} | BTC_LEG={addrs['BTC_LEGACY']} | ETH={addrs['ETH']} | SOL={addrs['SOL']} | TRX={addrs['TRX']}")


def main():
    parser = argparse.ArgumentParser(description='Investigate a single BIP39 seed: derive addresses and run balance checks.')
    parser.add_argument('--seed', '-s', help='BIP39 seed phrase (wrap in quotes). If omitted, will read from stdin.', default=None)
    parser.add_argument('--scan_addresses', type=int, default=int(os.getenv('SCAN_ADDRESSES', '20')),
                        help='Number of address indexes to derive per account (default from SCAN_ADDRESSES env or 20)')
    parser.add_argument('--scan_accounts', type=int, default=int(os.getenv('SCAN_ACCOUNTS', '1')),
                        help='Number of account indices to derive (default from SCAN_ACCOUNTS env or 1)')

    args = parser.parse_args()
    if args.seed:
        seed = args.seed.strip()
    else:
        print('Enter seed phrase (single line):')
        seed = sys.stdin.readline().strip()

    if not seed:
        print('No seed provided. Exiting.')
        return

    print(f"Deriving addresses for scan_addresses={args.scan_addresses}, scan_accounts={args.scan_accounts}")
    derived = derive_addresses(seed, args.scan_addresses, args.scan_accounts)
    print_derived(derived)

    # Run the full balance check using existing checker (will perform network calls)
    asyncio.run(run_check(seed))


if __name__ == '__main__':
    main()
