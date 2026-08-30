import re
import logging
import os
import concurrent.futures
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
        Extrai Seeds, Keys e Endereços diretos de forma otimizado para performance.
        Suporta varredura exaustiva de seeds contíguas e validação paralela para
        melhorar recall e velocidade em textos grandes.
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

        # 5. Seeds BIP39 — detecção reforçada: garantimos contiguidade, todos os tamanhos válidos,
        # e validação paralela dos candidatos para melhorar throughput em textos grandes.
        logger.info("🔍 Iniciando busca de seeds BIP39...")
        clean_text = re.sub(r'[^a-zA-Z\s]', ' ', text).lower()
        all_words = clean_text.split()
        total_words = len(all_words)
        logger.info(f"📊 Total de palavras no texto: {total_words}")

        # Encontramos seeds considerando apenas janelas contíguas do texto original.
        # Percorremos tamanhos válidos do BIP39 do maior para o menor para preferir seeds maiores
        # quando houver sobreposição.
        found_seeds: dict = {}
        if total_words >= 12:
            used = [False] * total_words
            bip39_sizes = [24, 21, 18, 15, 12]

            for size in bip39_sizes:
                if total_words < size:
                    continue
                logger.info(f"🔎 Buscando seeds de {size} palavras...")
                candidates = []
                limit = total_words - size + 1
                for i in range(limit):
                    # Pular janelas que já contenham índices marcados por uma seed maior
                    if any(used[i : i + size]):
                        continue
                    window = all_words[i : i + size]
                    # Só interessa se todas as palavras da janela pertencem ao BIP39
                    if not all(w in self.wordlist for w in window):
                        continue
                    phrase = " ".join(window)
                    candidates.append((i, phrase))

                logger.info(f"   Candidatos válidos (palavras presentes no wordlist): {len(candidates)}")

                # Valida candidatos em paralelo para acelerar checagem de checksum BIP39
                if candidates:
                    def validate(pair):
                        idx, phrase = pair
                        try:
                            if self.is_valid_bip39(phrase):
                                return (idx, phrase)
                        except:
                            return None
                        return None

                    max_workers = min(32, (os.cpu_count() or 1) * 5)
                    validated = []
                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                        # Map com chunks para reduzir overhead
                        for res in ex.map(validate, candidates, chunksize=64):
                            if res:
                                validated.append(res)

                    # Ordena validados por posição para determinismo
                    validated.sort(key=lambda x: x[0])

                    count = 0
                    for idx, phrase in validated:
                        # Checa novamente sobreposição (já que outras seeds validadas
                        # podem ter marcado índices)
                        if any(used[idx : idx + size]):
                            continue
                        # Marca índices como usados para evitar sobreposição por seeds menores
                        for j in range(idx, idx + size):
                            used[j] = True
                        found_seeds[phrase] = size
                        count += 1
                    logger.info(f"✅ Seeds de {size} palavras encontradas: {count}")
                else:
                    logger.info(f"✅ Seeds de {size} palavras encontradas: 0")

            logger.info(f"✅ Total de seeds BIP39 encontradas (sem sobreposições): {len(found_seeds)}")

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
