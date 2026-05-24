import re
from mnemonic import Mnemonic
import logging
import base58

logger = logging.getLogger(__name__)

class SeedExtractor:
    def __init__(self):
        self.mnemo = Mnemonic("english")
        self.wordlist = set(self.mnemo.wordlist)
    
    def is_valid_bip39(self, seed):
        try:
            return self.mnemo.check(seed)
        except:
            return False

    def extract_all(self, text):
        """
        Extrai Seeds BIP39 e Chaves Privadas (Base58/Hex).
        """
        if not text: return []
        
        results = []
        
        # 1. Extrair Seeds BIP39
        words = re.findall(r'[a-z]+', text.lower())
        valid_words = [w for w in words if w in self.wordlist]
        for length in [12, 24]:
            if len(valid_words) < length: continue
            for i in range(len(valid_words) - length + 1):
                phrase = " ".join(valid_words[i : i + length])
                if self.is_valid_bip39(phrase):
                    results.append(("SEED", phrase))
        
        # 2. Extrair Chaves Privadas Solana (Base58, ~88 chars ou 44 chars)
        sol_keys = re.findall(r'[1-9A-HJ-NP-Za-km-z]{43,88}', text)
        for key in sol_keys:
            try:
                decoded = base58.b58decode(key)
                if len(decoded) in [32, 64]:
                    results.append(("SOL_KEY", key))
            except: continue

        # 3. Extrair Chaves Privadas ETH (Hex 64 chars)
        eth_keys = re.findall(r'[0-9a-fA-F]{64}', text)
        for key in eth_keys:
            results.append(("ETH_KEY", key))

        # Remover duplicatas
        seen = set()
        unique_results = []
        for t, v in results:
            if v not in seen:
                unique_results.append((t, v))
                seen.add(v)
        
        return unique_results
