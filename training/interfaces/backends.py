from typing import Protocol, Optional, List


class ModelRunner(Protocol):
    """Backend-agnostic inference runner.

    Implementations should support loading a base model (optionally quantized),
    applying a PEFT adapter (or backend-specific adapter), and generating text
    from a prompt with optional system message and stop sequences.
    """

    def load_base(self, base_model: str, quantization: Optional[str] = "int4") -> None:
        ...

    def load_adapter(self, adapter_path: Optional[str]) -> None:
        ...

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
        stop: Optional[List[str]] = None,
    ) -> str:
        ...

