"""
Memory-friendly BIP39 seed extractor.

Uses sliding windows of exact BIP39 lengths (12/15/18/21/24) so a valid seed
is never swallowed by a larger invalid match (the previous greedy regex bug).
"""
from __future__ import annotations

import re
from typing import Iterator, Optional, Set

from bip_utils import Bip39MnemonicValidator

# BIP39 valid word counts (descending so longer seeds are preferred first)
BIP39_SIZES = (24, 21, 18, 15, 12)


class SeedExtractor:
    """
    Extract valid BIP39 English mnemonics from large text blobs.

    - Normalizes case / whitespace
    - Scans contiguous word windows of exact BIP39 sizes
    - Validates checksum with bip_utils (IsValid)
    - Deduplicates results
    - Processes in chunks to keep memory use bounded
    """

    def __init__(self, chunk_size: int = 100_000, overlap_words: int = 30):
        self.chunk_size = max(chunk_size, 1024)
        # enough overlap to not split a 24-word seed across chunk boundaries
        self.overlap_words = max(overlap_words, 30)
        self.validator = Bip39MnemonicValidator()

    def _normalize_words(self, text: str) -> list[str]:
        # keep only letters; collapse everything else to spaces
        clean = re.sub(r"[^a-zA-Z\s]", " ", text).lower()
        return clean.split()

    def _is_valid(self, phrase: str) -> bool:
        try:
            return bool(self.validator.IsValid(phrase))
        except Exception:
            return False

    def _scan_words(self, words: list[str], seen: Set[str], max_seeds: Optional[int]) -> Iterator[str]:
        n = len(words)
        if n < 12:
            return

        # mark indices already claimed by a longer seed to reduce overlap noise
        used = [False] * n

        for size in BIP39_SIZES:
            if n < size:
                continue
            for i in range(0, n - size + 1):
                if any(used[i : i + size]):
                    continue
                window = words[i : i + size]
                phrase = " ".join(window)
                if phrase in seen:
                    continue
                if self._is_valid(phrase):
                    seen.add(phrase)
                    for j in range(i, i + size):
                        used[j] = True
                    yield phrase
                    if max_seeds is not None and len(seen) >= max_seeds:
                        return

    def extract_all_iter(self, text: str, max_seeds: Optional[int] = None) -> Iterator[str]:
        """
        Yield valid mnemonics found in `text` one-by-one.
        Processes the text in overlapping character chunks for large inputs.
        """
        if not text or not text.strip():
            return

        seen: Set[str] = set()
        length = len(text)

        # For moderate texts, process everything at once (simpler + correct)
        if length <= self.chunk_size * 2:
            words = self._normalize_words(text)
            yield from self._scan_words(words, seen, max_seeds)
            return

        # Large text: sliding character chunks with word overlap
        pos = 0
        prev_tail_words: list[str] = []

        while pos < length:
            chunk = text[pos : pos + self.chunk_size]
            pos += self.chunk_size

            chunk_words = self._normalize_words(chunk)
            words = prev_tail_words + chunk_words

            yield from self._scan_words(words, seen, max_seeds)
            if max_seeds is not None and len(seen) >= max_seeds:
                return

            prev_tail_words = words[-self.overlap_words :] if len(words) > self.overlap_words else words

    def extract_all(self, text: str, max_seeds: Optional[int] = None) -> list[str]:
        """Convenience: return list of unique valid seeds."""
        return list(self.extract_all_iter(text, max_seeds=max_seeds))
