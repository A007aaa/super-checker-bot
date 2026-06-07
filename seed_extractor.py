import re
import logging
from mnemonic import Mnemonic
import base58

logger = logging.getLogger(__name__)

class SeedExtractor:
    def __init__(self):
        self.mnemo = Mnemonic("english")
        self.wordlist = set(self.mnemo.wordlist)

    def is_valid_bip39(self, seed):
        try:
            # Checksum rápido
            return self.mnemo.check(seed)
        except:
            return False

    def extract_all(self, text):
        """
        Extrai Seeds e Keys de forma otimizada para performance.
        """
        if not text:
            return []
        
        results = []
        
        # 1. Chaves Privadas (Regex é rápido)
        sol_keys = re.findall(r'[1-9A-HJ-NP-Za-km-z]{43,88}', text)
        for key in sol_keys:
            try:
                if len(base58.b58decode(key)) in [32, 64]:
                    results.append(("KEY_SOL", key))
            except: continue

        eth_keys = re.findall(r'(?:0x)?([0-9a-fA-F]{64})', text)
        for key in eth_keys:
            results.append(("KEY_HEX", key))

        # 2. Seeds BIP39 (Otimizado)
        clean_text = re.sub(r'[^a-zA-Z\s]', ' ', text).lower()
        all_words = clean_text.split()
        bip39_words = [w for w in all_words if w in self.wordlist]
        
        if len(bip39_words) >= 12:
            # Focamos em 12 e 24 palavras para performance em arquivos gigantes
            # Limitamos a busca para os primeiros 10.000 termos BIP39 encontrados
            max_search = min(len(bip39_words), 10000)
            
            # Buscamos primeiro sequências de 12 (mais comum)
            for i in range(max_search - 12 + 1):
                phrase = " ".join(bip39_words[i : i + 12])
                if self.is_valid_bip39(phrase):
                    results.append(("SEED", phrase))
            
            # Depois sequências de 24
            for i in range(max_search - 24 + 1):
                phrase = " ".join(bip39_words[i : i + 24])
                if self.is_valid_bip39(phrase):
                    results.append(("SEED", phrase))

        # Remover duplicatas
        seen = set()
        unique_results = []
        for t, v in results:
            if v not in seen:
                unique_results.append((t, v))
                seen.add(v)
        
        return unique_results
