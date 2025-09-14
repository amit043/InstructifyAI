from __future__ import annotations

import os
import sys
from typing import List


def parse_models_env() -> List[str]:
    models: List[str] = []
    env_models = os.environ.get("PREFETCH_MODELS", "").strip()
    if env_models:
        models.extend([m.strip() for m in env_models.split(",") if m.strip()])
    base = os.environ.get("BASE_MODEL")
    if base:
        models.append(base)
    # de-dup
    seen = set()
    out: List[str] = []
    for m in models:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def main() -> None:
    models = parse_models_env()
    if not models:
        print("[prefetch] No models to prefetch (set BASE_MODEL or PREFETCH_MODELS)")
        return
    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except Exception as e:
        print("[prefetch] huggingface_hub not available; skipping prefetch:", e)
        return

    token = os.environ.get("HF_TOKEN")
    for mid in models:
        # Skip GGUF repos (served by llama.cpp); only prefetch HF transformer repos
        if ".gguf" in mid.lower():
            print(f"[prefetch] Skipping GGUF path: {mid}")
            continue
        try:
            print(f"[prefetch] Downloading {mid} to HF cache...")
            snapshot_download(repo_id=mid, token=token, resume_download=True)
            print(f"[prefetch] Done: {mid}")
        except Exception as e:
            print(f"[prefetch] Failed to prefetch {mid}: {e}")


if __name__ == "__main__":
    main()

