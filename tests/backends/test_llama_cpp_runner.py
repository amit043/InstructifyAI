import os
import pytest


try:
    import llama_cpp  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pytest.skip("llama-cpp-python not installed; skipping llama.cpp backend tests", allow_module_level=True)


def test_llama_cpp_runner_interface():
    from backends.llama_cpp_runner import LlamaCppRunner

    r = LlamaCppRunner()
    assert hasattr(r, "load_base")
    assert hasattr(r, "load_adapter")
    assert hasattr(r, "generate")

    # Ensure adapter no-op does not raise
    r.load_adapter(None)

