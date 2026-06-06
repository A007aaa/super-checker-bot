import re
import logging
from mnemonic import Mnemonic

logger = logging.getLogger(__name__)

class SeedExtractor:
    def __init__(self):
        self.mnemo = Mnemonic("english")
        self.wordlist_set = set(self.mnemo.wordlist)

    def extract_all_seeds(self, text):
        if not text: return []
        
        # 1. Limpeza e Extração de Palavras
        # Pegamos apenas palavras que pertencem à lista BIP39 oficial
        all_words = re.findall(r'\b[a-z]{3,}\b', text.lower())
        valid_words = [w for w in all_words if w in self.wordlist_set]
        num_total = len(valid_words)
        
        seeds_found = set()
        
        # 2. Busca por Janela Deslizante (12 e 24 palavras são as principais)
        # Este método é ultra-rápido para listas onde as palavras estão em ordem
        for length in [12, 24, 15, 18, 21]:
            if num_total < length: continue
            for i in range(num_total - length + 1):
                phrase = " ".join(valid_words[i : i + length])
                if self.mnemo.check(phrase):
                    seeds_found.add(phrase)
        
        # 3. Busca por Blocos (Se a lista for enviada em linhas)
        # Algumas listas têm uma seed por linha mesmo com palavras extras
        lines = text.lower().splitlines()
        for line in lines:
            line_words = [w for w in re.findall(r'\b[a-z]{3,}\b', line) if w in self.wordlist_set]
            if len(line_words) >= 12:
                for length in [12, 24]:
                    if len(line_words) >= length:
                        for i in range(len(line_words) - length + 1):
                            phrase = " ".join(line_words[i : i + length])
                            if self.mnemo.check(phrase):
                                seeds_found.add(phrase)

        return list(seeds_found)
