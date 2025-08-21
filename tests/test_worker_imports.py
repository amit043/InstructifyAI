import importlib
import shutil

import pytest

MODULES = [
    "fitz",
    "pytesseract",
    "charset_normalizer",
    "bs4",
    "lxml",
    "httpx",
]


def test_python_deps_import() -> None:
    for mod in MODULES:
        pytest.importorskip(mod)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_tesseract_binary_present() -> None:
    assert shutil.which("tesseract")
