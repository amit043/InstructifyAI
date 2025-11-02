from __future__ import annotations

import io

import pytest
from PIL import Image

from core import settings as settings_module
from observability.metrics import OCR_FALLBACK_TOTAL
from services.ocr import orchestrator
from services.ocr.base import OCRResult, OCRUnavailableError
from services.ocr.deepseek_runner import DeepseekOCRRunner


def _sample_png() -> bytes:
    img = Image.new("RGB", (4, 4), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_deepseek_runner_transformers(monkeypatch):
    runner = DeepseekOCRRunner(model="deepseek-ai/DeepSeek-OCR")
    monkeypatch.setattr(runner, "_has_gpu", lambda: True)
    monkeypatch.setattr(runner, "_run_transformers", lambda *a, **k: "hello text")
    out = runner.run(_sample_png(), mode="text")
    assert out.text == "hello text"
    assert out.md == ""
    assert out.meta["runtime"] == "transformers"
    assert out.ctx_compressed


def test_deepseek_runner_markdown(monkeypatch):
    runner = DeepseekOCRRunner(model="deepseek-ai/DeepSeek-OCR")
    monkeypatch.setattr(runner, "_has_gpu", lambda: True)
    monkeypatch.setattr(runner, "_run_transformers", lambda *a, **k: "# Heading")
    out = runner.run(_sample_png(), mode="markdown")
    assert out.text == ""
    assert out.md == "# Heading"
    assert out.meta["mode"] == "markdown"


def test_run_ocr_fallbacks_to_paddle(monkeypatch):
    orchestrator.reset_ocr_runners()
    monkeypatch.setenv("OCR_BACKEND", "deepseek")
    monkeypatch.setenv("FEATURE_DEEPSEEK_OCR", "true")
    settings_module.get_settings.cache_clear()

    class _FailRunner:
        backend_name = "deepseek"

        def run(self, *_, **__):
            raise OCRUnavailableError("no gpu")

    class _PaddleStub:
        backend_name = "paddle"

        def run(self, *_, **__):
            return OCRResult(
                text="paddle text",
                md=None,
                meta={"backend": "paddle"},
                ctx_compressed=None,
            )

    monkeypatch.setattr(orchestrator, "_ensure_deepseek", lambda cfg: _FailRunner())
    monkeypatch.setattr(orchestrator, "_ensure_paddle", lambda: _PaddleStub())

    counter = OCR_FALLBACK_TOTAL.labels("deepseek", "paddle")
    before = counter._value.get()
    result = orchestrator.run_ocr(_sample_png(), mode="text", langs=["eng"])
    after = counter._value.get()

    assert result["text"] == "paddle text"
    assert after == pytest.approx(before + 1)

    orchestrator.reset_ocr_runners()
    settings_module.get_settings.cache_clear()
