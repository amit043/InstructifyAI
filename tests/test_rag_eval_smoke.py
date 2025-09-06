import json

from evals.runner import EvalExample, run
from evals.storage import EvalStorage


def test_rag_eval_smoke(tmp_path):
    dataset = [
        EvalExample(prompt="a", expected="a"),
        EvalExample(prompt="b", expected="c"),
    ]

    def model(prompt: str) -> str:
        return prompt

    storage = EvalStorage(tmp_path)
    metrics = run(dataset, model, storage, "r1")
    assert metrics["accuracy"] == 0.5
    data = json.loads((tmp_path / "r1.json").read_text())
    assert len(data["examples"]) == 2
    assert data["metrics"]["correct"] == 1
    index = json.loads((tmp_path / "index.json").read_text())
    assert index == ["r1"]
