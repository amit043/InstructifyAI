#!/usr/bin/env python3
"""CLI entry point for running prompt set evaluations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from evals.runner import EvalExample, run
from evals.storage import EvalStorage


def _load_dataset(path: Path) -> list[EvalExample]:
    examples: list[EvalExample] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        examples.append(EvalExample(prompt=data["prompt"], expected=data["expected"]))
    return examples


def echo_model(prompt: str) -> str:
    return prompt


MODELS: dict[str, Callable[[str], str]] = {"echo": echo_model}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run evaluation prompts")
    parser.add_argument(
        "--dataset", type=Path, required=True, help="Path to dataset JSONL"
    )
    parser.add_argument("--release", required=True, help="Release identifier")
    parser.add_argument("--model", choices=MODELS.keys(), default="echo")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("ui/evals/results"),
        help="Directory to store evaluation results",
    )
    args = parser.parse_args()

    dataset = _load_dataset(args.dataset)
    storage = EvalStorage(args.out)
    metrics = run(dataset, MODELS[args.model], storage, args.release)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
