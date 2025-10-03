from __future__ import annotations

import importlib.util
import sys
import types
import uuid
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "train_adapter.py"


def _load_module():
    module_name = f"train_adapter_test_module_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load train_adapter module spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def train_adapter_module():
    return _load_module()


def test_find_checkpoint_requires_existing_explicit(tmp_path, train_adapter_module):
    module = train_adapter_module
    explicit = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        module._find_checkpoint(str(tmp_path), str(explicit), True)


def test_find_checkpoint_respects_allow_resume(tmp_path, train_adapter_module):
    module = train_adapter_module
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    assert module._find_checkpoint(str(out_dir), None, False) is None


def test_find_checkpoint_prefers_transformers_checkpoint(monkeypatch, tmp_path, train_adapter_module):
    module = train_adapter_module
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    ckpt_dir = out_dir / "checkpoint-0001"
    ckpt_dir.mkdir()
    manual_ckpt = out_dir / module.MANUAL_CKPT_BASENAME
    manual_ckpt.write_text("stub", encoding="utf-8")

    trainer_utils = types.ModuleType("transformers.trainer_utils")
    trainer_utils.get_last_checkpoint = lambda _: str(ckpt_dir)
    transformers_mod = types.ModuleType("transformers")
    transformers_mod.trainer_utils = trainer_utils
    monkeypatch.setitem(sys.modules, "transformers", transformers_mod)
    monkeypatch.setitem(sys.modules, "transformers.trainer_utils", trainer_utils)

    result = module._find_checkpoint(str(out_dir), None, True)
    assert result == str(ckpt_dir.resolve())


def test_find_checkpoint_falls_back_to_manual(monkeypatch, tmp_path, train_adapter_module):
    module = train_adapter_module
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    manual_ckpt = out_dir / module.MANUAL_CKPT_BASENAME
    manual_ckpt.write_text("state", encoding="utf-8")

    trainer_utils = types.ModuleType("transformers.trainer_utils")
    trainer_utils.get_last_checkpoint = lambda _: None
    transformers_mod = types.ModuleType("transformers")
    transformers_mod.trainer_utils = trainer_utils
    monkeypatch.setitem(sys.modules, "transformers", transformers_mod)
    monkeypatch.setitem(sys.modules, "transformers.trainer_utils", trainer_utils)

    result = module._find_checkpoint(str(out_dir), None, True)
    assert result == str(manual_ckpt.resolve())


