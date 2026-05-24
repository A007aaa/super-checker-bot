import re
import logging
from mnemonic import Mnemonic
import base58

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
        # Normalizar texto: remover caracteres especiais e manter apenas letras e espaços
        clean_text = re.sub(r'[^a-zA-Z\s]', ' ', text).lower()
        all_words = clean_text.split()
        
        # Filtrar apenas palavras que pertencem à lista BIP39 oficial
        bip39_words = [w for w in all_words if w in self.wordlist]
        
        if len(bip39_words) >= 12:
            # Testar janelas de 12, 15, 18, 21 e 24 palavras (padrões BIP39)
            # Como o texto pode ser muito longo, limitamos a busca para eficiência
            max_words = min(len(bip39_words), 5000)
            valid_lengths = [12, 15, 18, 21, 24]
            
            for length in valid_lengths:
                for i in range(max_words - length + 1):
                    phrase = " ".join(bip39_words[i : i + length])
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
