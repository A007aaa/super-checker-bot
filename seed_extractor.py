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
            # Checksum rápido
            return self.mnemo.check(seed)
        except:
            return False

    def extract_all(self, text):
        """
        Extrai Seeds, Keys e Endereços diretos de forma otimizada para performance.
        Suporta até 1 milhão de seed phrases sem limite artificial.
        """
        if not text:
            return []
        
        results = []

        # 1. Endereços Ethereum (0x + 40 hex) — antes das chaves hex para evitar conflito
        eth_addrs = re.findall(r'\b(0x[0-9a-fA-F]{40})\b', text)
        for addr in eth_addrs:
            results.append(("ADDR_ETH", addr))

        # 2. Endereços Tron (T + 33 caracteres Base58)
        tron_addrs = re.findall(r'\b(T[1-9A-HJ-NP-Za-km-z]{33})\b', text)
        for addr in tron_addrs:
            results.append(("ADDR_TRON", addr))

        # 3. Endereços Bitcoin (bc1..., 1..., 3...)
        btc_addrs = re.findall(r'\b(bc1[a-zA-HJ-NP-Z0-9]{25,87}|[13][1-9A-HJ-NP-Za-km-z]{25,34})\b', text)
        for addr in btc_addrs:
            results.append(("ADDR_BTC", addr))

        # 4. Chaves Privadas (Regex é rápido)
        sol_keys = re.findall(r'[1-9A-HJ-NP-Za-km-z]{43,88}', text)
        for key in sol_keys:
            try:
                decoded = base58.b58decode(key)
                if len(decoded) in [32, 64]:
                    # Distinguir endereço Solana (32 bytes) de chave privada (64 bytes)
                    # Endereços Solana têm exatamente 43-44 caracteres Base58
                    if len(decoded) == 32 and 43 <= len(key) <= 44:
                        results.append(("ADDR_SOL", key))
                    else:
                        results.append(("KEY_SOL", key))
            except: continue

        eth_keys = re.findall(r'(?:0x)?([0-9a-fA-F]{64})', text)
        for key in eth_keys:
            results.append(("KEY_HEX", key))

        # 5. Seeds BIP39 — sem limite de palavras, suporta até 1 milhão
        logger.info("🔍 Iniciando busca de seeds BIP39...")
        clean_text = re.sub(r'[^a-zA-Z\s]', ' ', text).lower()
        all_words = clean_text.split()

        # Filtra apenas palavras BIP39 usando set para O(1) por lookup
        bip39_words = [w for w in all_words if w in self.wordlist]
        total_bip39 = len(bip39_words)
        logger.info(f"📊 Total de palavras BIP39 encontradas: {total_bip39}")

        if total_bip39 >= 12:
            # Dict de seeds encontradas: {seed: quantidade_de_palavras}
            # Permite saber o tamanho de cada seed para preferir a versão de
            # 24 palavras quando uma seed de 12 palavras estiver contida
            # (como prefixo) dentro de uma seed de 24 palavras válida.
            found_seeds: dict = {}

            # Buscamos primeiro sequências de 12 (mais comum)
            logger.info("🔎 Buscando seeds de 12 palavras...")
            seeds_12 = 0
            for i in range(total_bip39 - 12 + 1):
                if i > 0 and i % 10000 == 0:
                    logger.info(f"   Progresso: {i} / {total_bip39 - 12 + 1} | Seeds encontradas: {seeds_12}")
                phrase = " ".join(bip39_words[i : i + 12])
                if phrase not in found_seeds and self.is_valid_bip39(phrase):
                    found_seeds[phrase] = 12
                    seeds_12 += 1
            logger.info(f"✅ Seeds de 12 palavras encontradas: {seeds_12}")

            # Depois sequências de 24
            logger.info("🔎 Buscando seeds de 24 palavras...")
            seeds_24 = 0
            for i in range(total_bip39 - 24 + 1):
                if i > 0 and i % 10000 == 0:
                    logger.info(f"   Progresso: {i} / {total_bip39 - 24 + 1} | Seeds encontradas: {seeds_24}")
                phrase = " ".join(bip39_words[i : i + 24])
                if phrase in found_seeds:
                    continue
                if self.is_valid_bip39(phrase):
                    # Se a seed de 12 palavras que abre esta frase de 24 já foi
                    # encontrada, ela está contida (como prefixo) na de 24 —
                    # removemos a de 12 e mantemos apenas a de 24 (mais completa).
                    seed_12_prefix = " ".join(bip39_words[i : i + 12])
                    if found_seeds.get(seed_12_prefix) == 12:
                        del found_seeds[seed_12_prefix]
                        seeds_12 -= 1
                        logger.info(f"   ↪️ Seed de 12 palavras substituída pela de 24 (sobreposição detectada)")

                    found_seeds[phrase] = 24
                    seeds_24 += 1
            logger.info(f"✅ Seeds de 24 palavras encontradas: {seeds_24}")
            logger.info(f"✅ Total de seeds BIP39 encontradas (sem duplicatas/sobreposições): {len(found_seeds)}")

            for seed in found_seeds:
                results.append(("SEED", seed))

        # Remover duplicatas de todos os tipos usando set O(1)
        seen: set = set()
        unique_results = []
        for t, v in results:
            if v not in seen:
                unique_results.append((t, v))
                seen.add(v)

        # Estatísticas finais por tipo
        type_counts: dict = {}
        for t, _ in unique_results:
            type_counts[t] = type_counts.get(t, 0) + 1

        logger.info(f"📈 Total de itens únicos extraídos: {len(unique_results)}")
        for item_type in ["SEED", "ADDR_ETH", "ADDR_BTC", "ADDR_TRON", "ADDR_SOL", "KEY_SOL", "KEY_HEX"]:
            logger.info(f"   - {item_type}: {type_counts.get(item_type, 0)}")

        return unique_results
