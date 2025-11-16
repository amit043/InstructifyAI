from __future__ import annotations

import pytest
import torch

from backends.hf_runner import HFRunner


class DummyInputs(dict):
    def to(self, device):  # type: ignore[override]
        return self


class DummyTokenizer:
    eos_token_id = 0
    pad_token_id = 0

    def __call__(self, text, return_tensors="pt"):
        return DummyInputs({"input_ids": torch.tensor([[1]])})

    def decode(self, tokens, skip_special_tokens=True):
        return "decoded"


def _attach_runner_stubs(runner: HFRunner, model):
    runner.model = model  # type: ignore[assignment]
    runner.tokenizer = DummyTokenizer()  # type: ignore[assignment]


def test_generate_sampling_fallback_on_invalid_probabilities():
    runner = HFRunner()

    class Model:
        def __init__(self):
            self.device = "cpu"
            self.calls = []
            self._call_count = 0

        def generate(self, **kwargs):
            self.calls.append(kwargs)
            self._call_count += 1
            if self._call_count == 1:
                raise RuntimeError("probability tensor contains either `inf`, `nan` or element < 0")
            return torch.tensor([[1, 2]])

    model = Model()
    _attach_runner_stubs(runner, model)

    out = runner.generate("prompt", temperature=0.7)

    assert out == "decoded"
    assert model.calls[0]["do_sample"] is True
    assert model.calls[1]["do_sample"] is False


def test_generate_sampling_fallback_on_cuda_device_assert():
    runner = HFRunner()

    class Model:
        def __init__(self):
            self.device = "cuda"
            self.calls = []
            self._call_count = 0

        def generate(self, **kwargs):
            self.calls.append(kwargs)
            self._call_count += 1
            if self._call_count == 1:
                raise RuntimeError("CUDA error: device-side assert triggered")
            return torch.tensor([[1, 2]])

    model = Model()
    _attach_runner_stubs(runner, model)

    out = runner.generate("prompt", temperature=0.7)

    assert out == "decoded"
    assert model.calls[0]["do_sample"] is True
    assert model.calls[1]["do_sample"] is False


def test_generate_propagates_other_runtime_errors():
    runner = HFRunner()

    class Model:
        def __init__(self):
            self.device = "cpu"

        def generate(self, **kwargs):
            raise RuntimeError("some other failure")

    _attach_runner_stubs(runner, Model())

    with pytest.raises(RuntimeError, match="some other failure"):
        runner.generate("prompt", temperature=0)


def test_generate_strips_prompt_tokens_from_output():
    runner = HFRunner()

    class Model:
        def __init__(self):
            self.device = "cpu"

        def generate(self, **kwargs):
            # Pretend the model returned prompt tokens followed by two new tokens.
            return torch.tensor([[11, 22, 33, 44]])

    class Tokenizer(DummyTokenizer):
        def __call__(self, text, return_tensors="pt"):
            # Simulate an encoded prompt containing the first two ids.
            return DummyInputs({"input_ids": torch.tensor([[11, 22]])})

        def decode(self, tokens, skip_special_tokens=True):
            values = tokens.tolist() if hasattr(tokens, "tolist") else list(tokens)
            return f"decoded:{values}"

    runner.model = Model()  # type: ignore[assignment]
    runner.tokenizer = Tokenizer()  # type: ignore[assignment]

    out = runner.generate("prompt", temperature=0)

    assert out == "decoded:[33, 44]"
