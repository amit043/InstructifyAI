# span detection tests
from exporters.common import sanitize_export_text
from parsers.spans import detect_spans


def test_detects_fenced_code() -> None:
    text = "Here is code:\n```python\nprint('hi')\n```\nEnd"
    spans = detect_spans(text)
    codes = [s for s in spans if s.type == "code_fence"]
    assert codes and codes[0].text.startswith("```python")


def test_detects_latex_math() -> None:
    text = "Inline math $E=mc^2$ and display $$a^2+b^2=c^2$$"
    spans = detect_spans(text)
    texts = [s.text for s in spans if s.type == "math"]
    assert "$E=mc^2$" in texts
    assert "$$a^2+b^2=c^2$$" in texts


def test_detects_monospace_block() -> None:
    text = "    def add(x, y):\n        return x + y"
    spans = detect_spans(text)
    assert any(s.type == "monospace" for s in spans)


def test_sanitize_export_preserves_fence() -> None:
    code = "```\nprint('hi')\n```"
    assert sanitize_export_text(code) == code
    assert sanitize_export_text("  text ") == "text"
