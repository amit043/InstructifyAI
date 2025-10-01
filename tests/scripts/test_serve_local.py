from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from scripts.serve_local import _resolve_adapter_targets


def test_resolve_adapter_targets_for_peft_adapter(tmp_path):
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    (adapter_dir / "adapter_config.json").write_text("{}")

    adapter = SimpleNamespace(base_model="base-model-id")

    base_override, adapter_path = _resolve_adapter_targets(adapter, str(adapter_dir))

    assert base_override == "base-model-id"
    assert adapter_path == str(adapter_dir)


def test_resolve_adapter_targets_for_merged_model(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}")

    adapter = SimpleNamespace(base_model="unused")

    base_override, adapter_path = _resolve_adapter_targets(adapter, str(model_dir))

    assert base_override == str(model_dir)
    assert adapter_path is None


def test_resolve_adapter_targets_missing_configs(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    adapter = SimpleNamespace(base_model="base")

    with pytest.raises(HTTPException) as exc:
        _resolve_adapter_targets(adapter, str(empty_dir))

    assert exc.value.status_code == 500
