from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict
from urllib import request


@dataclass
class Notifier:
    """Simple HTTP webhook notifier with exponential backoff."""

    project_hooks: Dict[str, str] = field(default_factory=dict)
    timeout: float = 2.0
    max_retries: int = 3
    backoff_factor: float = 0.5

    def opt_in(self, project_id: str, url: str) -> None:
        self.project_hooks[project_id] = url

    def opt_out(self, project_id: str) -> None:
        self.project_hooks.pop(project_id, None)

    def notify(self, project_id: str, event: str, artifact_url: str) -> None:
        url = self.project_hooks.get(project_id)
        if not url:
            return
        payload = json.dumps({"event": event, "artifact_url": artifact_url}).encode()
        req = request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        for attempt in range(self.max_retries):
            try:
                request.urlopen(req, timeout=self.timeout)
                break
            except Exception:
                if attempt == self.max_retries - 1:
                    raise
                sleep_for = self.backoff_factor * (2**attempt)
                time.sleep(sleep_for)


_notifier: Notifier | None = None


def get_notifier() -> Notifier:
    global _notifier
    if _notifier is None:
        _notifier = Notifier()
    return _notifier
