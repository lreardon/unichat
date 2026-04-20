from packages.ingestion.chunking.token_counter import estimate_tokens


class TestTokenCounter:
    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 0

    def test_single_word(self) -> None:
        assert estimate_tokens("hello") == 1  # int(1 * 1.3) = 1

    def test_typical_sentence(self) -> None:
        text = "The quick brown fox jumps over the lazy dog"
        # 9 words * 1.3 = 11.7 → 11
        result = estimate_tokens(text)
        assert 10 <= result <= 15

    def test_longer_text(self) -> None:
        words = ["word"] * 100
        text = " ".join(words)
        result = estimate_tokens(text)
        # 100 * 1.3 = 130
        assert result == 130

    def test_proportional_scaling(self) -> None:
        short = estimate_tokens("one two three")
        long = estimate_tokens("one two three four five six")
        assert long > short
