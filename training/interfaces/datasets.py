from typing import Protocol, Literal
from datasets import DatasetDict, Dataset


TaskType = Literal["qa", "extraction", "classification"]


class DatasetBuilder(Protocol):
    """Builds HuggingFace datasets from InstructifyAI exports for a specific task.

    Implementations take an export JSONL path and return a DatasetDict with
    at least "train" and "validation" splits. Records should contain the
    fields required by the downstream trainer (e.g., a formatted "text" field
    for SFT-style training).
    """

    def build(
        self, *, input_path: str, task: TaskType, split_ratio: float = 0.1
    ) -> DatasetDict:
        ...


class PrefDataset(Protocol):
    """Yields (prompt, chosen, rejected) triples for ORPO/DPO-style alignment.

    Implementations should load pairs/triples from a JSONL path and return a
    single-split Dataset where each example contains string fields:
    - prompt
    - chosen
    - rejected
    """

    def build(self, *, input_path: str) -> Dataset:
        ...

