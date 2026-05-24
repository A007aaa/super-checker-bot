import re
from mnemonic import Mnemonic
import logging
import base58
import itertools

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

    def extract_all(self, text):
        """
        Extrai Seeds BIP39 (mesmo misturadas) e Chaves Privadas.
        """
        if not text: return []
        
        results = []
        
        # Normalizar texto: remover caracteres especiais e manter apenas letras e espaços
        clean_text = re.sub(r'[^a-z\s]', ' ', text.lower())
        all_words = clean_text.split()
        
        # 1. Extrair Seeds BIP39 (Lógica de Janela Deslizante + Inteligência de Filtro)
        # Filtramos apenas palavras que pertencem à lista BIP39
        valid_words_in_text = [w for w in all_words if w in self.wordlist]
        
        # Tenta janelas de 12, 15, 18, 21 e 24 palavras
        for length in [12, 15, 18, 21, 24]:
            if len(valid_words_in_text) < length: continue
            for i in range(len(valid_words_in_text) - length + 1):
                phrase = " ".join(valid_words_in_text[i : i + length])
                if self.is_valid_bip39(phrase):
                    results.append(("SEED", phrase))
        
        # 2. Lógica para "Seeds Misturadas" (Heurística de proximidade)
        # Se houver muitas palavras BIP39 próximas mas com "lixo" no meio, tentamos limpar
        if len(valid_words_in_text) >= 12:
            # Pegamos blocos de palavras próximas no texto original que são BIP39
            # e tentamos formar seeds válidas ignorando o lixo entre elas
            pass # Implementação futura de permutação se necessário

        # 3. Extrair Chaves Privadas Solana (Base58)
        sol_keys = re.findall(r'[1-9A-HJ-NP-Za-km-z]{43,88}', text)
        for key in sol_keys:
            try:
                decoded = base58.b58decode(key)
                if len(decoded) in [32, 64]:
                    results.append(("SOL_KEY", key))
            except: continue

        # 4. Extrair Chaves Privadas ETH (Hex 64 chars)
        eth_keys = re.findall(r'(?:0x)?([0-9a-fA-F]{64})', text)
        for key in eth_keys:
            results.append(("ETH_KEY", key))

        # Remover duplicatas mantendo a ordem
        seen = set()
        unique_results = []
        for t, v in results:
            if v not in seen:
                unique_results.append((t, v))
                seen.add(v)
        
        return unique_results
