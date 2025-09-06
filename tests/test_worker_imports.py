def test_worker_dependencies_import() -> None:
    import importlib

    modules = [
        "fitz",  # PyMuPDF
        "pytesseract",
        "charset_normalizer",
        "bs4",
        "lxml",
        "httpx",
    ]

    for mod in modules:
        assert importlib.import_module(mod) is not None
