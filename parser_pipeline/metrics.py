from __future__ import annotations

import unicodedata


def char_coverage(text: str) -> dict[str, float | int]:
    """Calculate character coverage ratios for a text.

    Ratios are computed over non-surrogate characters. Surrogate code
    points are skipped and tallied separately under ``invalid_count``.
    The return dictionary includes ratios for ASCII, Latin-1, and other
    character sets.
    """
    ascii_count = 0
    latin1_count = 0
    other_count = 0
    invalid_count = 0

    for ch in text:
        if unicodedata.category(ch) == "Cs":
            invalid_count += 1
            continue
        code = ord(ch)
        if code <= 0x7F:
            ascii_count += 1
        elif code <= 0xFF:
            latin1_count += 1
        else:
            other_count += 1

    total = ascii_count + latin1_count + other_count
    if total == 0:
        return {
            "ascii_ratio": 0.0,
            "latin1_ratio": 0.0,
            "other_ratio": 0.0,
            "invalid_count": invalid_count,
        }
    return {
        "ascii_ratio": ascii_count / total,
        "latin1_ratio": latin1_count / total,
        "other_ratio": other_count / total,
        "invalid_count": invalid_count,
    }


__all__ = ["char_coverage"]
