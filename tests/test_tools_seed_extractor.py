"""Regression tests for tools.seed_extractor.SeedExtractor."""
from tools.seed_extractor import SeedExtractor

VALID_12 = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)
VALID_12B = "legal winner thank year wave sausage worth useful legal winner thank yellow"


def test_exact_seed():
    seeds = SeedExtractor().extract_all(VALID_12)
    assert VALID_12 in seeds
    assert len(seeds) == 1


def test_seed_with_trailing_noise():
    """Previous greedy-regex bug: extra words made the only match invalid."""
    text = VALID_12 + " hello world more noise"
    seeds = SeedExtractor().extract_all(text)
    assert VALID_12 in seeds


def test_multiple_seeds():
    text = VALID_12 + " foo bar " + VALID_12B
    seeds = SeedExtractor().extract_all(text)
    assert VALID_12 in seeds
    assert VALID_12B in seeds
    assert len(seeds) >= 2


def test_invalid_text():
    seeds = SeedExtractor().extract_all("not a real seed phrase with twelve words here now")
    assert seeds == []


def test_empty():
    assert SeedExtractor().extract_all("") == []
    assert SeedExtractor().extract_all("   ") == []


if __name__ == "__main__":
    test_exact_seed()
    test_seed_with_trailing_noise()
    test_multiple_seeds()
    test_invalid_text()
    test_empty()
    print("All tests passed.")
