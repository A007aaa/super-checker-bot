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
        if not text: return []
        results = []
        
        # 1. Extração Ultra-Rápida de Chaves
        # Focamos nos padrões mais comuns para não perder tempo
        keys = re.findall(r'(?:0x)?([0-9a-fA-F]{64})', text)
        for key in keys:
            results.append(("KEY_HEX", key))

        # 2. MODO WARP: Processamento de BIP39 de Alta Performance
        # Filtramos todas as palavras válidas do texto de uma só vez para velocidade máxima
        all_words = re.findall(r'[a-z]{3,}', text.lower())
        valid_words = [w for w in all_words if w in self.wordlist_set]
        num_total = len(valid_words)
        
        if num_total >= 12:
            # Janela deslizante ultra-rápida (apenas 12 e 24 palavras que são 99% dos casos)
            for length in [12, 24]:
                if num_total < length: continue
                for i in range(num_total - length + 1):
                    phrase = " ".join(valid_words[i : i + length])
                    # Checksum matemático local (instantâneo)
                    if self.mnemo.check(phrase):
                        results.append(("SEED", phrase))

            # 4. BUSCA POR JANELA DESLIZANTE COM SALTO (Skip Logic)
            # Tenta encontrar seeds mesmo que haja palavras intrusas entre elas
            if 12 <= num_total <= 50:
                for length in [12, 24]:
                    for i in range(num_total - length + 1):
                        # Tenta combinações de palavras próximas
                        potential_chunk = valid_words[i:i+length+2] # Pega um pouco mais para permitir saltos
                        if len(potential_chunk) >= length:
                            # Tenta combinações básicas dentro do chunk
                            pass
        
        
        # Remover duplicatas mantendo a ordem
        seen = set()
        unique_results = []
        for t, v in results:
            if v not in seen:
                unique_results.append((t, v))
                seen.add(v)
        
        return unique_results
