from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class EvalStorage:
    """Persist evaluation results per release as JSON files.

    Results are stored under ``root`` with one ``<release>.json`` file
    containing the examples and summary metrics. An ``index.json`` file
    tracks the list of releases for simple UI lookup.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def save(
        self,
        release: str,
        examples: list[dict[str, Any]],
        metrics: dict[str, Any],
    ) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        data = {"examples": examples, "metrics": metrics}
        (self.root / f"{release}.json").write_text(json.dumps(data, indent=2))
        index_path = self.root / "index.json"
        if index_path.exists():
            releases = json.loads(index_path.read_text())
        else:
            releases = []
        if release not in releases:
            releases.append(release)
            index_path.write_text(json.dumps(releases, indent=2))
