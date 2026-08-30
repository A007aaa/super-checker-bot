import pytest
from mnemonic import Mnemonic
from seed_extractor import SeedExtractor

mn = Mnemonic("english")

# Maps strength to expected word counts:
# 128 -> 12, 160 -> 15, 192 -> 18, 224 -> 21, 256 -> 24

def make_seed(strength_bits):
    return mn.generate(strength=strength_bits)

@pytest.mark.parametrize("strength_bits", [128, 160, 192, 224, 256])
def test_seed_detected_at_far_position(strength_bits):
    seed = make_seed(strength_bits)
    # Put the seed after a large filler to ensure extractor doesn't truncate search
    filler = "word " * 20000
    text = filler + " " + seed + " " + filler
    se = SeedExtractor(allow_mismatch=0)
    results = dict(se.extract_all(text))
    assert seed in results, f"Seed of strength {strength_bits} not found"


def test_fuzzy_detection_with_one_typo():
    # Only run fuzzy test if allow_mismatch is supported
    seed = make_seed(160)  # 15-word seed
    words = seed.split()
    # introduce one small typo into the 8th word
    corrupt = words.copy()
    corrupt[7] = corrupt[7][:-1] + 'x' if len(corrupt[7]) > 3 else corrupt[7] + 'x'
    corrupt_seed = ' '.join(corrupt)
    filler = 'word ' * 5000
    text = filler + ' ' + corrupt_seed + ' ' + filler
    # allow_mismatch=1 should attempt to correct one word
    se = SeedExtractor(allow_mismatch=1)
    results = dict(se.extract_all(text))
    # The extractor may correct the typo and return the canonical seed
    assert any(len(s.split()) in (15, ) for t, s in se.extract_all(text) if t == 'SEED')
