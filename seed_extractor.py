import re
from mnemonic import Mnemonic

class SeedExtractor:
    def __init__(self):
        self.mnemo = Mnemonic("english")
        self.wordlist = set(self.mnemo.wordlist)
        self.lengths = [24, 21, 18, 15, 12]
    
    def check_seed(self, seed):
        """Retorna (is_valid, error_msg)"""
        words = seed.split()
        if len(words) not in self.lengths:
            return False, f"Tamanho inválido ({len(words)} palavras)"
        
        # Verificar se todas as palavras existem na lista BIP39
        for w in words:
            if w not in self.wordlist:
                return False, f"Palavra inválida: {w}"
        
        # Verificar Checksum
        if not self.mnemo.check(seed):
            return False, "Checksum inválido (frase incorreta)"
            
        return True, "OK"

    def extract_all_seeds(self, text):
        if not text: return []
        
        # Limpeza: manter apenas letras minúsculas e espaços
        clean_text = re.sub(r'[^a-z\s]', ' ', text.lower())
        words = clean_text.split()
        
        found_raw = []
        
        # Busca por sequências de palavras da wordlist
        for length in self.lengths:
            for i in range(len(words) - length + 1):
                segment = words[i:i + length]
                if all(word in self.wordlist for word in segment):
                    found_raw.append(" ".join(segment))
        
        # Remover duplicatas
        seen = set()
        unique = []
        for s in found_raw:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        
        return unique
