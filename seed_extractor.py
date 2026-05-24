import re
import logging
from mnemonic import Mnemonic
import base58
from rapidfuzz import process, fuzz

logger = logging.getLogger(__name__)

class SeedExtractor:
    def __init__(self):
        self.mnemo = Mnemonic("english")
        self.wordlist = list(self.mnemo.wordlist) # Convert to list for rapidfuzz
        self.wordlist_set = set(self.mnemo.wordlist) # Keep set for fast exact lookups

    def is_valid_bip39(self, seed):
        try:
            return self.mnemo.check(seed)
        except:
            return False

    def extract_all(self, text):
        """
        Extrai Seeds BIP39 (mesmo misturadas ou em blocos) e Chaves Privadas.
        """
        if not text:
            return []
        
        results = []
        
        # 1. Extrair Chaves Privadas Solana (Base58)
        # Solana usa Base58, geralmente entre 43 e 88 caracteres
        sol_keys = re.findall(r'[1-9A-HJ-NP-Za-km-z]{43,88}', text)
        for key in sol_keys:
            try:
                # Verificação básica de decodificação para evitar falsos positivos
                decoded = base58.b58decode(key)
                if len(decoded) in [32, 64]:
                    results.append(("KEY_SOL", key))
            except:
                continue

        # 2. Extrair Chaves Privadas ETH/BTC (Hex 64 chars)
        eth_keys = re.findall(r'(?:0x)?([0-9a-fA-F]{64})', text)
        for key in eth_keys:
            results.append(("KEY_HEX", key))

        # 3. Lógica Avançada para Seeds BIP39
        # Normalizar texto: manter letras e espaços, mas também tratar camelCase ou colados
        # Substitui qualquer coisa que não seja letra por espaço
        clean_text = re.sub(r'[^a-z]+', ' ', text.lower())
        all_words = clean_text.split()
        
        # Filtrar palavras que pertencem à wordlist BIP39
        # Vamos manter a posição original para tentar janelas contíguas
        words_with_pos = []
        for i, word in enumerate(all_words):
            if word in self.wordlist_set:
                words_with_pos.append(word)
            elif len(word) >= 3:
                # Fuzzy matching apenas para palavras com tamanho razoável
                match = process.extractOne(word, self.wordlist, scorer=fuzz.ratio, score_cutoff=95)
                if match:
                    words_with_pos.append(match[0])
        
        # Tentativa de encontrar sequências válidas de 12 a 24 palavras
        if len(words_with_pos) >= 12:
            valid_lengths = [12, 15, 18, 21, 24]
            for length in valid_lengths:
                # Janela deslizante sobre as palavras encontradas
                for i in range(len(words_with_pos) - length + 1):
                    phrase = " ".join(words_with_pos[i : i + length])
                    if self.is_valid_bip39(phrase):
                        results.append(("SEED", phrase))

        # Remover duplicatas mantendo a ordem de descoberta
        seen = set()
        unique_results = []
        for t, v in results:
            if v not in seen:
                unique_results.append((t, v))
                seen.add(v)
        
        return unique_results

if __name__ == "__main__":
    # Teste de unidade simples
    extractor = SeedExtractor()
    sample = "house apple ... (muito texto) ... "
    # print(extractor.extract_all(sample))
