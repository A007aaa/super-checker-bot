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
        """
        Extrai todas as combinações possíveis de seeds BIP39 de um texto (sopa de letras).
        A estratégia é filtrar apenas palavras válidas do BIP39 e testar janelas deslizantes.
        """
        if not text: return []
        
        # 1. Limpeza agressiva: extrair apenas palavras que pertencem à wordlist BIP39
        # Isso transforma a "sopa de letras" em uma sequência pura de palavras candidatas.
        clean_text = re.sub(r'[^a-z\s]', ' ', text.lower())
        all_words = clean_text.split()
        bip39_words = [word for word in all_words if word in self.wordlist]
        
        if not bip39_words:
            return []

        found_seeds = []
        
        # 2. Busca por Janela Deslizante (Sliding Window)
        # Testamos todas as sequências possíveis de 12, 15, 18, 21 e 24 palavras.
        total_words = len(bip39_words)
        for length in self.lengths:
            if total_words < length:
                continue
            for i in range(total_words - length + 1):
                segment = bip39_words[i : i + length]
                seed_phrase = " ".join(segment)
                if self.is_valid_bip39(seed_phrase):
                    found_seeds.append(seed_phrase)
        
        # 3. Busca por Combinações Espalhadas (Opcional/Avançado)
        # Se as palavras da seed estiverem intercaladas com OUTRAS palavras BIP39 que não fazem parte dela,
        # a janela deslizante ainda funcionará se a distância for pequena.
        # Para casos extremos de "sopa", a janela deslizante sobre a lista filtrada é a melhor abordagem custo-benefício.

        # Remover duplicatas mantendo a ordem de descoberta
        seen = set()
        return [x for x in found_seeds if not (x in seen or seen.add(x))]
