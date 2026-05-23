import re
from mnemonic import Mnemonic

class SeedExtractor:
    def __init__(self):
        self.bip39_list = set(Mnemonic("english").wordlist)
        self.lengths = [24, 21, 18, 15, 12]
    
    def extract_seeds_from_text(self, text):
        """Extrai seeds de texto com palavras separadas por espaço"""
        words = re.findall(r'\b[a-z]+\b', text.lower())
        return self._find_seeds_in_words(words)
    
    def extract_seeds_from_joined(self, text):
        """Extrai seeds de texto com palavras juntas (sem espaço)"""
        text = text.lower()
        seeds = []
        
        for length in self.lengths:
            seeds.extend(self._find_joined_seeds(text, length))
        
        return list(set(seeds))
    
    def _find_joined_seeds(self, text, length):
        """Encontra seeds em texto sem espaços"""
        seeds = []
        
        for start in range(len(text)):
            words = []
            pos = start
            
            while len(words) < length and pos < len(text):
                found = False
                
                # Tenta palavras de 3 a 15 caracteres
                for word_len in range(3, 16):
                    if pos + word_len <= len(text):
                        potential_word = text[pos:pos + word_len]
                        
                        if potential_word in self.bip39_list:
                            words.append(potential_word)
                            pos += word_len
                            found = True
                            break
                
                if not found:
                    break
            
            if len(words) == length:
                seed = " ".join(words)
                if seed not in seeds:
                    seeds.append(seed)
        
        return seeds
    
    def _find_seeds_in_words(self, words):
        """Encontra seeds em lista de palavras"""
        potential_seeds = []
        
        for length in self.lengths:
            for i in range(len(words) - length + 1):
                segment = words[i:i + length]
                
                if all(word in self.bip39_list for word in segment):
                    seed = " ".join(segment)
                    if seed not in potential_seeds:
                        potential_seeds.append(seed)
        
        return potential_seeds
    
    def extract_all_seeds(self, text):
        """Extrai todas as seeds possíveis do texto"""
        seeds = []
        
        # Tenta extrair de texto com espaços
        seeds.extend(self.extract_seeds_from_text(text))
        
        # Tenta extrair de texto sem espaços
        seeds.extend(self.extract_seeds_from_joined(text))
        
        # Remove duplicatas mantendo ordem
        seen = set()
        unique_seeds = []
        for seed in seeds:
            if seed not in seen:
                seen.add(seed)
                unique_seeds.append(seed)
        
        return unique_seeds
