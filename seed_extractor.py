import re
from mnemonic import Mnemonic
import logging

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

    def extract_all_seeds(self, text):
        """
        Extrai de forma ultra-agressiva todas as combinações de 12 e 24 palavras.
        """
        if not text: return []
        
        # Limpeza radical: mantém apenas palavras a-z
        words = re.findall(r'[a-z]+', text.lower())
        
        # Filtra apenas palavras que existem no dicionário BIP39
        valid_words = [w for w in words if w in self.wordlist]
        total = len(valid_words)
        
        found_seeds = []
        # Testa janelas de 12 e 24 palavras (as mais comuns)
        for length in [12, 24]:
            if total < length: continue
            for i in range(total - length + 1):
                phrase = " ".join(valid_words[i : i + length])
                if self.is_valid_bip39(phrase):
                    found_seeds.append(phrase)
        
        # Remove duplicatas
        seen = set()
        return [x for x in found_seeds if not (x in seen or seen.add(x))]
