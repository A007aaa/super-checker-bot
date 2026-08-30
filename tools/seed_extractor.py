"""
Memory-friendly BIP39 seed extractor.

Uses sliding windows of exact BIP39 lengths (12/15/18/21/24) so a valid seed
is never swallowed by a larger invalid match.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator, Optional, Set

from bip_utils import Bip39MnemonicValidator, Bip39Languages

BIP39_SIZES = (24, 21, 18, 15, 12)


@dataclass
class ExtractStats:
    valid: list[str] = field(default_factory=list)
    failed_checksum: list[str] = field(default_factory=list)  # look like seeds but invalid
    total_words: int = 0
    windows_scanned: int = 0


class SeedExtractor:
    def __init__(self, chunk_size: int = 100_000, overlap_words: int = 30):
        self.chunk_size = max(chunk_size, 1024)
        self.overlap_words = max(overlap_words, 30)
        self.validator = Bip39MnemonicValidator()

    def _normalize_words(self, text: str) -> list[str]:
        # letters only; numbers/punct -> space (keeps BIP39 english words)
        clean = re.sub(r"[^a-zA-Z\s]", " ", text).lower()
        return clean.split()

    def _is_valid(self, phrase: str) -> bool:
        try:
            return bool(self.validator.IsValid(phrase))
        except Exception:
            return False

    def _all_bip39_words(self, words: list[str]) -> bool:
        """True if every word is in the English BIP39 wordlist."""
        try:
            # bip_utils validates word-by-word via full mnemonic; fallback: try each size-1 trick
            from bip_utils.bip.bip39.bip39_mnemonic import Bip39WordsListGetter

            wl = set(Bip39WordsListGetter.GetInstance().GetByLanguage(Bip39Languages.ENGLISH))
            return all(w in wl for w in words)
        except Exception:
            # if wordlist helper fails, don't mark as failed_checksum
            return False

    def _scan_words(
        self,
        words: list[str],
        seen: Set[str],
        stats: ExtractStats,
        max_seeds: Optional[int],
    ) -> Iterator[str]:
        n = len(words)
        if n < 12:
            return

        used = [False] * n

        for size in BIP39_SIZES:
            if n < size:
                continue
            for i in range(0, n - size + 1):
                if any(used[i : i + size]):
                    continue
                window = words[i : i + size]
                phrase = " ".join(window)
                stats.windows_scanned += 1
                if phrase in seen:
                    continue
                if self._is_valid(phrase):
                    seen.add(phrase)
                    stats.valid.append(phrase)
                    for j in range(i, i + size):
                        used[j] = True
                    yield phrase
                    if max_seeds is not None and len(seen) >= max_seeds:
                        return
                else:
                    # só registra se TODAS as palavras são BIP39 (checksum que falhou)
                    if (
                        len(stats.failed_checksum) < 20
                        and self._all_bip39_words(window)
                        and phrase not in stats.failed_checksum
                    ):
                        stats.failed_checksum.append(phrase)

    def extract_with_stats(
        self, text: str, max_seeds: Optional[int] = None
    ) -> ExtractStats:
        stats = ExtractStats()
        if not text or not text.strip():
            return stats

        seen: Set[str] = set()
        length = len(text)

        if length <= self.chunk_size * 2:
            words = self._normalize_words(text)
            stats.total_words = len(words)
            list(self._scan_words(words, seen, stats, max_seeds))
            return stats

        pos = 0
        prev_tail_words: list[str] = []
        all_word_count = 0

        while pos < length:
            chunk = text[pos : pos + self.chunk_size]
            pos += self.chunk_size
            chunk_words = self._normalize_words(chunk)
            words = prev_tail_words + chunk_words
            all_word_count += len(chunk_words)
            list(self._scan_words(words, seen, stats, max_seeds))
            if max_seeds is not None and len(seen) >= max_seeds:
                break
            prev_tail_words = (
                words[-self.overlap_words :] if len(words) > self.overlap_words else words
            )

        stats.total_words = all_word_count
        return stats

    def extract_all_iter(self, text: str, max_seeds: Optional[int] = None) -> Iterator[str]:
        stats = self.extract_with_stats(text, max_seeds=max_seeds)
        yield from stats.valid

    def extract_all(self, text: str, max_seeds: Optional[int] = None) -> list[str]:
        return self.extract_with_stats(text, max_seeds=max_seeds).valid
