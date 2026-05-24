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
        
        # 1. Extrair todas as palavras que são válidas no BIP39 wordlist, mantendo a ordem
        bip39_words = [word for word in all_words_in_text if word in self.wordlist]
        
        if not bip39_words:
            return []

        # 2. Busca Exaustiva: Janela Deslizante sobre as palavras BIP39
        # Isso cobre o caso onde as palavras da seed estão em sequência, mesmo com lixo entre elas
        for length in self.lengths:
            for i in range(len(bip39_words) - length + 1):
                segment = bip39_words[i : i + length]
                seed_phrase = " ".join(segment)
                if self.is_valid_bip39(seed_phrase):
                    found_seeds.append(seed_phrase)
        
        # 3. Busca por "Lixo Extremo": 
        # Se as palavras da seed estiverem muito espalhadas, a janela deslizante sobre bip39_words resolve.
        # Mas se houver palavras que NÃO são BIP39 no meio, a limpeza inicial já as removeu.
        # O que pode estar acontecendo é a seed estar "quebrada" por palavras que TAMBÉM são BIP39 mas não fazem parte da seed.
        
        # Para lidar com isso, o bot já está testando todas as janelas possíveis dentro da lista de palavras BIP39.
        # Ex: se o texto é "word1 LIXO word2 word3 ... word12", bip39_words será ["word1", "word2", ..., "word12"]
        # e a janela deslizante vai capturar isso perfeitamente.

        # Remover duplicatas mantendo a ordem de descoberta
        seen = set()
        return [x for x in found_seeds if not (x in seen or seen.add(x))]
