"""Model catalog and simple recommender.

This module defines a small, extensible catalog of base models and exposes
utilities to recommend a model + quantization + context length based on
detected hardware. It aims to be conservative and robust across Docker and
Windows hosts, relying only on the `hw` dict contract provided by
`core.hw.detect_hardware()`.

Data model notes:
- Each catalog entry includes `id`, `hf_id`, `params_b`, `ctx`, and recommended
  quants with approximate VRAM requirements. A CPU-only GGUF entry is also
  provided with approximate RAM guidance.

Recommendation policy (heuristic, easy to refine later):
- If CUDA is available and VRAM >= 12GB → prefer 7B–8B in int4.
- Else if CUDA VRAM >= 6GB → prefer a 3B–4B class int4 model (Phi-3-mini here).
- Else → fall back to CPU `llama_cpp` GGUF.

Token cap heuristic (very rough, for safety):
- For int4 7B on ~8–12GB VRAM: 2048–4096 new tokens (bounded by ctx/2).
- For smaller VRAM or CPU gguf: 512–1024 new tokens (bounded by ctx/2).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# Small, opinionated catalog. Extend as needed.
CATALOG: List[Dict[str, Any]] = [
    {
        "id": "mistral-7b-instruct",
        "hf_id": "mistralai/Mistral-7B-Instruct-v0.3",
        "params_b": 7,
        "ctx": 8192,
        "recommended_quant": ["int4", "fp16"],
        "min_vram_mb": {"int4": 5500, "fp16": 14000},
    },
    {
        "id": "llama-3-8b-instruct",
        "hf_id": "meta-llama/Meta-Llama-3-8B-Instruct",
        "params_b": 8,
        "ctx": 8192,
        "recommended_quant": ["int4", "fp16"],
        "min_vram_mb": {"int4": 6500, "fp16": 16000},
    },
    {
        "id": "phi-3-mini-4k-instruct",
        "hf_id": "microsoft/Phi-3-mini-4k-instruct",
        "params_b": 2.8,
        "ctx": 4096,
        "recommended_quant": ["int4", "fp16"],
        "min_vram_mb": {"int4": 2500, "fp16": 6000},
    },
    # CPU-only GGUF entry (for llama.cpp)
    {
        "id": "mistral-7b-instruct-gguf-q4_k_m",
        # Example consolidated reference (repo/file-style string for convenience)
        "gguf": "TheBloke/Mistral-7B-Instruct.Q4_K_M.gguf",
        "params_b": 7,
        "ctx": 4096,
        "recommended_quant": ["gguf"],
        # Approx system RAM guidance, not strict.
        "min_ram_gb": 8,
    },
]


def _get_entry(model_id: str) -> Optional[Dict[str, Any]]:
    for e in CATALOG:
        if e.get("id") == model_id:
            return e
    return None


def _choose_gpu_model(vram_mb: int, preference: str = "small") -> Dict[str, Any]:
    """Choose a GPU model based on available VRAM.

    Preference can be used to bias selection among similarly sized models.
    Recognized values: "small" (default), "balanced", "quality".
    """
    # Tier 1: 12GB+ VRAM → 7B–8B int4
    if vram_mb >= 12000:
        if preference in {"quality", "balanced"}:
            return _get_entry("llama-3-8b-instruct") or _get_entry("mistral-7b-instruct")  # type: ignore[return-value]
        return _get_entry("mistral-7b-instruct") or _get_entry("llama-3-8b-instruct")  # type: ignore[return-value]

    # Tier 2: 6GB–12GB → 3B–4B class int4 (Phi-3-mini here)
    if vram_mb >= 6000:
        return _get_entry("phi-3-mini-4k-instruct")  # type: ignore[return-value]

    # If we get here, caller should fall back to CPU/gguf.
    return {}


def recommend_for_hw(hw: Dict[str, Any], preference: str = "small") -> Dict[str, Any]:
    """Recommend a runtime backend + base model + quant + ctx for given hardware.

    Parameters
    - hw: dict as returned by `core.hw.detect_hardware()`.
    - preference: optional bias among choices ("small", "balanced", "quality").

    Returns
    - {"backend": "hf"|"llama_cpp", "base_model": str, "quant": "int4"|"fp16"|"gguf", "ctx": int}
    """

    has_cuda = bool(hw.get("has_cuda", False))
    vram_mb = hw.get("vram_mb")
    vram_mb = int(vram_mb) if isinstance(vram_mb, (int, float)) else None

    # GPU path
    if has_cuda and vram_mb is not None and vram_mb > 0:
        entry = _choose_gpu_model(vram_mb, preference=preference)
        if entry:
            # Default to int4 for safety; allow fp16 if preference requests and VRAM allows.
            quant = "int4"
            if preference in {"quality", "fp16"}:
                req = entry.get("min_vram_mb", {}).get("fp16")
                if isinstance(req, int) and vram_mb >= req:
                    quant = "fp16"
            return {
                "backend": "hf",
                "base_model": entry["hf_id"],
                "quant": quant,
                "ctx": int(entry.get("ctx", 4096)),
            }

    # CPU fallback: llama.cpp with GGUF
    gguf_entry = _get_entry("mistral-7b-instruct-gguf-q4_k_m")
    if gguf_entry:
        return {
            "backend": "llama_cpp",
            "base_model": gguf_entry["gguf"],
            "quant": "gguf",
            "ctx": int(gguf_entry.get("ctx", 4096)),
        }

    # Ultimate fallback (should not happen with current catalog)
    # use the smallest HF model to ensure something reasonable is returned.
    entry = _get_entry("phi-3-mini-4k-instruct") or _get_entry("mistral-7b-instruct")
    if entry:
        return {
            "backend": "hf",
            "base_model": entry["hf_id"],
            "quant": "int4",
            "ctx": int(entry.get("ctx", 4096)),
        }

    return {"backend": "llama_cpp", "base_model": "", "quant": "gguf", "ctx": 2048}


def cap_tokens_for_hw(hw: Dict[str, Any], ctx: int) -> int:
    """Cap the number of new tokens for generation for safety.

    Heuristic rules:
    - If CPU gguf → cap 512–1024 (depending on CPU RAM and context), <= ctx/2.
    - If GPU int4 7B on ~8–12GB → 2048; >=12–16GB → 4096 (bounded by ctx/2).
    - For lower VRAM or fp16, be conservative and cap at 1024–2048.
    """
    ctx = max(256, int(ctx))
    has_cuda = bool(hw.get("has_cuda", False))
    vram_mb = hw.get("vram_mb")
    vram_mb = int(vram_mb) if isinstance(vram_mb, (int, float)) else None

    # CPU path
    if not has_cuda or not vram_mb or vram_mb <= 0:
        # Assume CPU RAM might be the bottleneck; keep conservative.
        cap = 1024 if ctx >= 2048 else 512
        return min(cap, ctx // 2)

    # GPU path
    if vram_mb < 6000:
        # Very small VRAM; be very conservative
        return min(768, ctx // 2)
    if 6000 <= vram_mb < 12000:
        # ~3B–4B int4 tier
        return min(1024, ctx // 2)
    if 12000 <= vram_mb < 16000:
        # 7B–8B int4 but tighter VRAM
        return min(2048, ctx // 2)
    # 16GB+ VRAM
    return min(4096, ctx // 2)


__all__ = ["CATALOG", "recommend_for_hw", "cap_tokens_for_hw"]

