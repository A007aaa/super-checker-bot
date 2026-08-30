import time
from mnemonic import Mnemonic
from seed_extractor import SeedExtractor

mn = Mnemonic("english")


def run_once(seed_words, n_filler_words=10000, allow_mismatch=0):
    filler = "word " * n_filler_words
    text = filler + " " + seed_words + " " + filler
    se = SeedExtractor(allow_mismatch=allow_mismatch)
    t0 = time.time()
    results = se.extract_all(text)
    elapsed = time.time() - t0
    stats = getattr(se, "last_stats", {})
    print(f"size={len(seed_words.split())} words, filler={n_filler_words}, mismatch={allow_mismatch} -> elapsed={elapsed:.2f}s, stats={stats}")
    return results, stats


if __name__ == "__main__":
    # generate representatives: 12/15/18/21/24 words
    seeds = [
        " ".join(mn.generate(strength=128).split()[:12]),
        " ".join(mn.generate(strength=160).split()[:15]),
        " ".join(mn.generate(strength=192).split()[:18]),
        " ".join(mn.generate(strength=224).split()[:21]),
        mn.generate(strength=256),
    ]
    for seed in seeds:
        run_once(seed, n_filler_words=10000, allow_mismatch=0)
