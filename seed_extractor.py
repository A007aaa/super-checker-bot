import re
from mnemonic import Mnemonic

class SeedExtractor:
    def __init__(self):
        self.mnemo = Mnemonic("english")
        self.wordlist = set(self.mnemo.wordlist)
        self.lengths = [24, 21, 18, 15, 12]
    
    def is_valid_bip39(self, seed):
        """Verifica se a frase é uma seed BIP39 válida (incluindo checksum)."""
        try:
            return self.mnemo.check(seed)
        except:
            return False

    def extract_all_seeds(self, text):
        if not text: return []
        
        # Limpeza: manter apenas letras minúsculas e espaços
        clean_text = re.sub(r'[^a-z\s]', ' ', text.lower())
        words = clean_text.split()
        
        found_seeds = []
        
        # Busca por sequências de palavras válidas (Janela Deslizante)
        # Este método é muito mais preciso para listas grandes
        for length in self.lengths:
            for i in range(len(words) - length + 1):
                segment = words[i:i + length]
                # Verifica se todas as palavras do segmento estão na wordlist BIP39
                if all(word in self.wordlist for word in segment):
                    seed = " ".join(segment)
                    # SÓ ADICIONA SE O CHECKSUM FOR VÁLIDO
                    if self.is_valid_bip39(seed):
                        found_seeds.append(seed)
        
        # Remover duplicatas mantendo a ordem
        seen = set()
        return [x for x in found_seeds if not (x in seen or seen.add(x))]
