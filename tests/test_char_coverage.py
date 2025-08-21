import pytest

from parser_pipeline.metrics import char_coverage


def test_char_coverage_mixed() -> None:
    text = "ABCé漢\ud800"
    metrics = char_coverage(text)
    assert metrics["invalid_count"] == 1
    assert metrics["ascii_ratio"] == pytest.approx(3 / 5)
    assert metrics["latin1_ratio"] == pytest.approx(1 / 5)
    assert metrics["other_ratio"] == pytest.approx(1 / 5)


def test_char_coverage_all_invalid() -> None:
    text = "\ud800\udfff"
    metrics = char_coverage(text)
    assert metrics["invalid_count"] == 2
    assert metrics["ascii_ratio"] == 0.0
    assert metrics["latin1_ratio"] == 0.0
    assert metrics["other_ratio"] == 0.0
