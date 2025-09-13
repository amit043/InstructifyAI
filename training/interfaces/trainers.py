from typing import Protocol, Optional, Dict, Any
from datasets import DatasetDict


class TrainerStrategy(Protocol):
    """Generic trainer for supervised finetuning-compatible data."""

    def train(
        self,
        *,
        base_model: str,
        output_dir: str,
        data: DatasetDict,
        peft_cfg: Optional[Dict[str, Any]] = None,
        quantization: Optional[str] = None,
        max_seq_len: int = 2048,
        lr: float = 2e-4,
        num_epochs: int = 1,
        batch_size: int = 1,
        grad_accum: int = 16,
        eval_dataset_key: str = "validation",
    ) -> Dict[str, Any]:
        """Runs training and returns a metrics dict.

        Implementations should persist artifacts to ``output_dir`` and return
        basic metrics including at minimum train/eval loss if available.
        """


class PreferenceTrainer(Protocol):
    """Trainer for ORPO-like alignment using (prompt, chosen, rejected)."""

    def train(
        self,
        *,
        base_model: str,
        output_dir: str,
        pref_data,  # HF Dataset
        peft_cfg: Optional[Dict[str, Any]] = None,
        quantization: Optional[str] = None,
        max_seq_len: int = 2048,
        lr: float = 5e-5,
        num_epochs: int = 1,
        batch_size: int = 1,
        grad_accum: int = 16,
    ) -> Dict[str, Any]:
        ...

