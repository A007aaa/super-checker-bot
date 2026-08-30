import re
import logging
import os
import time
import difflib
import concurrent.futures
from mnemonic import Mnemonic
import base58

logger = logging.getLogger(__name__)

class SeedExtractor:
    def __init__(self, allow_mismatch: int = 0):
        """
        allow_mismatch: number of words per window to attempt fuzzy correction for (0 = disabled).
        Currently only small values (0 or 1) are practical due to combinatorics.
        """
        self.mnemo = Mnemonic("english")
        self.wordlist = list(self.mnemo.wordlist)
        self.wordset = set(self.wordlist)
        self.allow_mismatch = max(0, int(allow_mismatch))
        self.last_stats = {}

    def is_valid_bip39(self, seed):
        try:
            # Checksum rápido
            return self.mnemo.check(seed)
        except:
            return False

    def _fuzzy_replace_candidates(self, window, max_replacements=1):
        """
        Given a list of words (window), find candidate corrected phrases by replacing
        up to max_replacements words with close matches from the wordlist.
        Uses difflib.get_close_matches as a heuristic (fast).
        Returns an iterator of candidate phrases (strings).
        Note: caller should limit usage to small max_replacements (0 or 1) to avoid blowup.
        """
        # indices of words not in wordset
        unknown_idxs = [i for i, w in enumerate(window) if w not in self.wordset]
        if not unknown_idxs:
            return []
        if len(unknown_idxs) > max_replacements:
            return []

        # For each unknown word, get close matches (up to 5)
        replacements = {}
        for idx in unknown_idxs:
            w = window[idx]
            # cutoff 0.8 is heuristic; lower it to allow more permissive matches
            matches = difflib.get_close_matches(w, self.wordlist, n=5, cutoff=0.78)
            if not matches:
                # no good match -> try phonetic simplification: remove punctuation/numbers
                simple = re.sub(r'[^a-z]', '', w)
                if simple and simple != w:
                    matches = difflib.get_close_matches(simple, self.wordlist, n=5, cutoff=0.78)
            if matches:
                replacements[idx] = matches
            else:
                # cannot correct this word
                return []

        # Build candidate phrases by Cartesian product of matches for unknown indices
        from itertools import product
        lists = [replacements[i] for i in unknown_idxs]
        candidates = []
        for combo in product(*lists):
            new_window = list(window)
            for idx, repl in zip(unknown_idxs, combo):
                new_window[idx] = repl
            candidates.append(" ".join(new_window))
        return candidates

    def extract_all(self, text):
        """
        Extrai Seeds, Keys e Endereços diretos de forma otimizada para performance.
        Suporta varredura exaustiva de seeds contíguas, validação paralela, normalização
        e tentativa fuzzy opcional para aumentar recall em casos de OCR/ruído.
        The method sets self.last_stats with telemetry about the last run.
        """
        start_time = time.time()
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
        # normalização e validação paralela dos candidatos para melhorar throughput em textos grandes.
        logger.info("🔍 Iniciando busca de seeds BIP39...")
        # Normalização: remover caracteres não-alfabéticos, lower-case, collapse spaces
        clean_text = re.sub(r"[^a-zA-Z\s]", ' ', text).lower()
        clean_text = re.sub(r"\s+", ' ', clean_text).strip()
        all_words = clean_text.split()
        total_words = len(all_words)
        logger.info(f"📊 Total de palavras no texto: {total_words}")

        # Telemetry counters
        windows_checked = 0
        candidates_total = 0
        validated_total = 0

        # Encontramos seeds considerando apenas janelas contíguas do texto original.
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
                    windows_checked += 1
                    # Pular janelas que já contenham índices marcados por uma seed maior
                    if any(used[i : i + size]):
                        continue
                    window = all_words[i : i + size]
                    # Count how many words are not in wordlist - allows fuzzy attempts
                    non_words = [w for w in window if w not in self.wordset]
                    if non_words:
                        if self.allow_mismatch <= 0:
                            continue
                        if len(non_words) > self.allow_mismatch:
                            continue
                    # If all words are in set, add straightforward candidate
                    if not non_words:
                        phrase = " ".join(window)
                        candidates.append((i, phrase, False))  # (idx, phrase, fuzzy_flag)
                    else:
                        # Add as fuzzy candidate (will attempt corrections later)
                        phrase = " ".join(window)
                        candidates.append((i, phrase, True))

                candidates_total += len(candidates)
                logger.info(f"   Candidatos válidos (com/sem fuzzy): {len(candidates)}")

                # Valida candidatos em paralelo para acelerar checagem de checksum BIP39
                if candidates:
                    def validate(item):
                        idx, phrase, is_fuzzy = item
                        # direct validation
                        if not is_fuzzy:
                            if self.is_valid_bip39(phrase):
                                return (idx, phrase)
                            return None
                        # fuzzy: attempt corrections (only practical for small allow_mismatch)
                        if self.allow_mismatch <= 0:
                            return None
                        # try fuzzy replacements
                        window_words = phrase.split()
                        corrected_phrases = self._fuzzy_replace_candidates(window_words, max_replacements=self.allow_mismatch)
                        for cand in corrected_phrases:
                            if self.is_valid_bip39(cand):
                                return (idx, cand)
                        return None

                    max_workers = min(32, (os.cpu_count() or 1) * 5)
                    validated = []
                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
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
                        validated_total += 1
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

        elapsed = time.time() - start_time
        self.last_stats = {
            'time_seconds': elapsed,
            'total_words': total_words,
            'windows_checked': windows_checked,
            'candidates_total': candidates_total,
            'validated_total': validated_total,
            'seeds_found': len([1 for t, _ in unique_results if t == 'SEED'])
        }

        logger.info(f"📈 Total de itens únicos extraídos: {len(unique_results)} | tempo: {elapsed:.2f}s")
        for item_type in ["SEED", "ADDR_ETH", "ADDR_BTC", "ADDR_TRON", "ADDR_SOL", "KEY_SOL", "KEY_HEX"]:
            logger.info(f"   - {item_type}: {type_counts.get(item_type, 0)}")

        return unique_results
