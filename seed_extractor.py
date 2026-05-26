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
        
        # 1. Extração de Chaves (Hex e Base58) - Rápido
        keys = re.findall(r'[1-9A-HJ-NP-Za-km-z]{43,88}|(?:0x)?([0-9a-fA-F]{64})', text)
        for key in keys:
            if isinstance(key, tuple): key = key[0] or key[1]
            if not key: continue
            if len(key) == 64: results.append(("KEY_HEX", key))
            else:
                try:
                    if len(base58.b58decode(key)) in [32, 64]: results.append(("KEY_SOL", key))
                except: pass

        # 2. MODO HYPER TURBO: Processamento de BIP39
        # Melhoria: Processa o texto mantendo a estrutura de blocos para não misturar seeds
        # Dividimos o texto por quebras de linha ou múltiplos espaços para isolar possíveis seeds
        blocks = re.split(r'\n+|,|;| {2,}', text.lower())
        
        # Primeiro, tentamos a busca por blocos (mais rápida e organizada)
        for block in blocks:
            clean_block = re.sub(r'[^a-z]+', ' ', block)
            words = clean_block.split()
            valid_words = [w for w in words if w in self.wordlist_set]
            num_words = len(valid_words)
            if num_words >= 12:
                for length in [12, 15, 18, 21, 24]:
                    if num_words < length: continue
                    for i in range(num_words - length + 1):
                        phrase = " ".join(valid_words[i : i + length])
                        if self.mnemo.check(phrase): results.append(("SEED", phrase))

        # Segundo, tentamos a busca global (para listas totalmente embaralhadas sem quebras de linha)
        all_clean = re.sub(r'[^a-z]+', ' ', text.lower())
        all_valid_words = [w for w in all_clean.split() if w in self.wordlist_set]
        num_total = len(all_valid_words)
        if num_total >= 12:
            for length in [12, 15, 18, 21, 24]:
                if num_total < length: continue
                for i in range(num_total - length + 1):
                    phrase = " ".join(all_valid_words[i : i + length])
                    if self.mnemo.check(phrase): results.append(("SEED", phrase))

            # 4. BUSCA POR JANELA DESLIZANTE COM SALTO (Skip Logic)
            # Tenta encontrar seeds mesmo que haja palavras intrusas entre elas
            if 12 <= num_words <= 50:
                for length in [12, 24]:
                    for i in range(num_words - length + 1):
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
