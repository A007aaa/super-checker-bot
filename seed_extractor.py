import re
from mnemonic import Mnemonic
import logging

logger = logging.getLogger(__name__)

class SeedExtractor:
    def __init__(self):
        self.mnemo = Mnemonic("english")
        self.wordlist = set(self.mnemo.wordlist)
        self.lengths = [12, 15, 18, 21, 24]
    
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
        all_words_in_text = clean_text.split()
        
        found_seeds = []
        
        # Extrair todas as palavras que são válidas no BIP39 wordlist, mantendo a ordem
        bip39_words_with_indices = [(word, i) for i, word in enumerate(all_words_in_text) if word in self.wordlist]
        
        # Iterar sobre todas as palavras BIP39 encontradas como possíveis inícios de uma seed
        for i in range(len(bip39_words_with_indices)):
            for length in self.lengths:
                # Verificar se há palavras BIP39 suficientes para formar uma seed do comprimento atual
                if i + length <= len(bip39_words_with_indices):
                    # Pegar o segmento de palavras BIP39
                    potential_seed_segment_info = bip39_words_with_indices[i : i + length]
                    potential_seed_words = [word for word, _ in potential_seed_segment_info]
                    
                    seed_phrase = " ".join(potential_seed_words)
                    
                    # Validar a seed phrase
                    if self.is_valid_bip39(seed_phrase):
                        found_seeds.append(seed_phrase)
        
        # Remover duplicatas mantendo a ordem de descoberta
        seen = set()
        return [x for x in found_seeds if not (x in seen or seen.add(x))]
