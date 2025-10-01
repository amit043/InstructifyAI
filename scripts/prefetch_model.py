import os
import sys
from pathlib import Path

try:
    from huggingface_hub import snapshot_download
except Exception as e:
    print("huggingface_hub is required in the container to prefetch models.")
    raise


def main() -> int:
    model = os.environ.get("HF_MODEL") or os.environ.get("BASE_MODEL")
    if not model:
        print("HF_MODEL/BASE_MODEL not set; nothing to prefetch.")
        return 1

    cache_dir = os.environ.get("HF_HOME") or os.environ.get("TRANSFORMERS_CACHE") or "/opt/hf"
    Path(cache_dir).mkdir(parents=True, exist_ok=True)

    token = os.environ.get("HUGGING_FACE_HUB_TOKEN") or os.environ.get("HF_TOKEN")

    print(f"[prefetch] Downloading {model} -> {cache_dir}")
    try:
        snapshot_download(
            repo_id=model,
            local_dir=cache_dir,
            local_dir_use_symlinks=False,
            token=token,
            resume_download=True,
        )
        print("[prefetch] Done")
        return 0
    except Exception as e:
        print(f"[prefetch] Failed: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

