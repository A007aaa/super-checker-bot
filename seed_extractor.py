import re
import logging
from mnemonic import Mnemonic
import base58
from rapidfuzz import process, fuzz

logger = logging.getLogger(__name__)

class SeedExtractor:
    def __init__(self):
        self.mnemo = Mnemonic("english")
        self.wordlist = list(self.mnemo.wordlist)
        self.wordlist_set = set(self.mnemo.wordlist)

    def is_valid_bip39(self, seed):
        try:
            return self.mnemo.check(seed)
        except:
            return False

    def extract_all_seeds(self, text):
        results = self.extract_all(text)
        return [val for type, val in results if type == "SEED"]

    def extract_all(self, text):
        if not text:
            return []
        
        results = []
        
        # 1. Chaves Privadas Solana (Base58)
        sol_keys = re.findall(r'[1-9A-HJ-NP-Za-km-z]{43,88}', text)
        for key in sol_keys:
            try:
                decoded = base58.b58decode(key)
                if len(decoded) in [32, 64]:
                    results.append(("KEY_SOL", key))
            except: continue

        # 2. Chaves Privadas ETH/BTC (Hex 64)
        eth_keys = re.findall(r'(?:0x)?([0-9a-fA-F]{64})', text)
        for key in eth_keys:
            results.append(("KEY_HEX", key))

        # 3. FORÇA BRUTA BIP39
        # Remove TUDO que não é letra, converte para minúsculo
        clean_text = re.sub(r'[^a-z]+', ' ', text.lower())
        words = clean_text.split()
        
        # Filtra apenas o que é ou parece palavra BIP39
        potential_words = []
        for w in words:
            if w in self.wordlist_set:
                potential_words.append(w)
            elif len(w) >= 3:
                # Fuzzy matching para erros de digitação (90% de similaridade)
                match = process.extractOne(w, self.wordlist, scorer=fuzz.ratio, score_cutoff=90)
                if match:
                    potential_words.append(match[0])

        # Se tivermos pelo menos 12 palavras, tentamos todas as combinações de janelas
        # Força bruta: tenta janelas de 12, 15, 18, 21 e 24 em QUALQUER posição
        num_words = len(potential_words)
        if num_words >= 12:
            valid_lengths = [12, 15, 18, 21, 24]
            for length in valid_lengths:
                if num_words >= length:
                    for i in range(num_words - length + 1):
                        phrase = " ".join(potential_words[i : i + length])
                        if self.is_valid_bip39(phrase):
                            results.append(("SEED", phrase))
        
        # Remover duplicatas mantendo a ordem
        seen = set()
        unique_results = []
        for t, v in results:
            if v not in seen:
                unique_results.append((t, v))
                seen.add(v)
        
        return unique_results
