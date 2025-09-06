#!/usr/bin/env python3
"""Generate example bundle files from base64 sources."""
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLES_DIR = ROOT / "examples" / "bundles"

FILES = {
    "mixed.pdf": BUNDLES_DIR / "mixed.pdf.b64",
    "sample.zip": BUNDLES_DIR / "sample.zip.b64",
}


def main() -> None:
    BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
    for out_name, b64_path in FILES.items():
        out_path = BUNDLES_DIR / out_name
        if not out_path.exists():
            data = base64.b64decode(b64_path.read_text())
            out_path.write_bytes(data)


if __name__ == "__main__":
    main()
