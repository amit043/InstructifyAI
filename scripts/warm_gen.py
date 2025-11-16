from __future__ import annotations

import json
import sys

from scripts.serve_local import perform_warmup


def main() -> int:
    result = perform_warmup()
    print(json.dumps(result, indent=2))
    status = result.get("status")
    if status == "failed":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
