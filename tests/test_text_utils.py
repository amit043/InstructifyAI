from text.normalize import chunk_by_tokens, normalize_text, simhash64, token_len


def test_normalize_basic() -> None:
    s = "A\u00adB  \n  C\ufb01"
    out = normalize_text(s)
    assert out == "AB Cfi"


def test_token_len_and_chunk() -> None:
    text = "one two three four five six seven eight nine ten"
    assert token_len(text) >= 10
    chunks = chunk_by_tokens(text, target=4, overlap=1)
    assert chunks
    # ensure overlap produces more than one chunk
    assert len(chunks) >= 3


def test_simhash_similarity() -> None:
    a = "The quick brown fox jumps over the lazy dog"
    b = "The quick brown fox jumped over a very lazy dog"
    ha = simhash64(a)
    hb = simhash64(b)
    # Hamming distance small for similar sentences
    dist = bin(ha ^ hb).count("1")
    assert dist <= 32
