import re
from typing import Iterator, Optional
from bip_utils import Bip39MnemonicValidator


class SeedExtractor:
    """
    SeedExtractor provides a memory-friendly iterator to extract valid BIP39
    mnemonics from a large text blob. It is purposefully tolerant (lowercasing,
    collapsing whitespace) and validates candidates with Bip39MnemonicValidator.

    Use extract_all_iter(large_text) to iterate over discovered seeds one-by-one.
    """

    # match sequences of 12..24 words consisting of ascii letters only
    CANDIDATE_RE = re.compile(r"\b([a-zA-Z]+(?:\s+[a-zA-Z]+){11,23})\b")

    def __init__(self, chunk_size: int = 65536, overlap: int = 512):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.validator = Bip39MnemonicValidator()

    def _normalize(self, s: str) -> str:
        # lower-case and collapse whitespace
        return " ".join(s.strip().lower().split())

    def extract_all_iter(self, text: str, max_seeds: Optional[int] = None) -> Iterator[str]:
        """
        Iterate over valid mnemonics found in `text`.
        This processes `text` in sliding chunks so it does not run expensive
        global regex over the entire string at once (helps responsiveness).
        """
        found = 0
        buffer = ""
        pos = 0
        length = len(text)

        while pos < length:
            chunk = text[pos: pos + self.chunk_size]
            pos += self.chunk_size
            block = buffer + chunk

            for m in self.CANDIDATE_RE.finditer(block):
                cand = self._normalize(m.group(1))
                try:
                    # IsValid returns bool; Validate() returns None on success and raises on failure
                    if self.validator.IsValid(cand):
                        yield cand
                        found += 1
                        if max_seeds and found >= max_seeds:
                            return
                except Exception:
                    # skip invalid candidate
                    continue

            # keep tail for overlap
            if len(block) > self.overlap:
                buffer = block[-self.overlap:]
            else:
                buffer = block

        # final pass on buffer
        for m in self.CANDIDATE_RE.finditer(buffer):
            cand = self._normalize(m.group(1))
            try:
                if self.validator.IsValid(cand):
                    yield cand
                    found += 1
                    if max_seeds and found >= max_seeds:
                        return
            except Exception:
                continue
