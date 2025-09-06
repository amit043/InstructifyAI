from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from .storage import EvalStorage


@dataclass
class EvalExample:
    prompt: str
    expected: str


def run(
    dataset: Sequence[EvalExample],
    model: Callable[[str], str],
    storage: EvalStorage,
    release: str,
) -> dict[str, float]:
    """Run the dataset against ``model`` and persist the results."""
    examples: list[dict[str, object]] = []
    correct = 0
    for item in dataset:
        answer = model(item.prompt)
        is_correct = answer.strip() == item.expected.strip()
        examples.append(
            {
                "prompt": item.prompt,
                "expected": item.expected,
                "answer": answer,
                "correct": is_correct,
            }
        )
        if is_correct:
            correct += 1
    total = len(dataset)
    accuracy = correct / total if total else 0.0
    metrics = {"total": total, "correct": correct, "accuracy": accuracy}
    storage.save(release, examples, metrics)
    return metrics
