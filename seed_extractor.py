import re
from mnemonic import Mnemonic

class SeedExtractor:
    def __init__(self):
        self.mnemo = Mnemonic("english")
        self.wordlist = set(self.mnemo.wordlist)
        self.lengths = [24, 21, 18, 15, 12]
    
    def is_valid_bip39(self, seed):
        """Verifica se a frase é uma seed BIP39 válida (incluindo checksum)."""
        return self.mnemo.check(seed)

    def extract_all_seeds(self, text):
        if not text: return []
        
        # Limpeza inicial: converter para minúsculas e remover caracteres estranhos, mantendo apenas letras e espaços
        clean_text = re.sub(r'[^a-z\s]', ' ', text.lower())
        words = clean_text.split()
        
        found_seeds = []
        
        # 1. Busca por sequências de palavras válidas (Método Deslizante)
        for length in self.lengths:
            for i in range(len(words) - length + 1):
                segment = words[i:i + length]
                # Verifica se todas as palavras do segmento estão na wordlist BIP39
                if all(word in self.wordlist for word in segment):
                    seed = " ".join(segment)
                    if self.is_valid_bip39(seed):
                        found_seeds.append(seed)
        
        # 2. Busca por seeds "grudadas" (sem espaços)
        # Este método é mais lento, então usamos apenas se o texto for pequeno ou se não acharmos nada
        if not found_seeds and len(text) < 5000:
            found_seeds.extend(self._extract_joined(text.lower()))
            
        # Remover duplicatas mantendo a ordem
        seen = set()
        return [x for x in found_seeds if not (x in seen or seen.add(x))]

    def _extract_joined(self, text):
        # Remove tudo que não for letra
        text = re.sub(r'[^a-z]', '', text)
        seeds = []
        
        for length in self.lengths:
            for start in range(len(text)):
                words = []
                pos = start
                while len(words) < length and pos < len(text):
                    found_word = False
                    # BIP39 words têm entre 3 e 8 letras
                    for l in range(8, 2, -1):
                        word = text[pos:pos+l]
                        if word in self.wordlist:
                            words.append(word)
                            pos += l
                            found_word = True
                            break
                    if not found_word: break
                
                if len(words) == length:
                    seed = " ".join(words)
                    if self.is_valid_bip39(seed):
                        seeds.append(seed)
        return seeds
