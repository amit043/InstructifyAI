from __future__ import annotations

"""Minimal REST client for Label Studio."""

import itertools
from typing import Iterable

import requests  # type: ignore[import-untyped]


class LabelStudioClient:
    """Tiny helper around the Label Studio REST API."""

    def __init__(self, base_url: str, api_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Token {api_token}"}

    # internal helper
    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def upsert_project(self, slug: str, title: str | None = None) -> dict:
        """Return an existing project by slug or create it."""
        resp = requests.get(
            self._url("/api/projects"),
            params={"slug": slug},
            headers=self.headers,
        )
        resp.raise_for_status()
        data = resp.json()
        projects = data["results"] if isinstance(data, dict) and "results" in data else data
        for proj in projects:
            if proj.get("slug") == slug:
                return proj
        payload = {"title": title or slug, "slug": slug}
        resp = requests.post(
            self._url("/api/projects"), headers=self.headers, json=payload
        )
        resp.raise_for_status()
        return resp.json()

    def set_project_config(self, project_id: int, config: str) -> None:
        resp = requests.patch(
            self._url(f"/api/projects/{project_id}"),
            headers=self.headers,
            json={"label_config": config},
        )
        resp.raise_for_status()

    def create_tasks(
        self, project_id: int, tasks: Iterable[dict], batch_size: int = 100
    ) -> int:
        """Create tasks in batches. Returns count created."""
        total = 0
        iterator = iter(tasks)
        while True:
            batch = list(itertools.islice(iterator, batch_size))
            if not batch:
                break
            resp = requests.post(
                self._url(f"/api/projects/{project_id}/tasks/bulk"),
                headers=self.headers,
                json=batch,
            )
            resp.raise_for_status()
            total += len(batch)
        return total

    def ensure_webhook(self, project_id: int, url: str) -> None:
        """Ensure a webhook exists for the given project/url."""
        resp = requests.get(
            self._url("/api/webhooks"),
            headers=self.headers,
            params={"project": project_id},
        )
        resp.raise_for_status()
        data = resp.json()
        hooks = data["results"] if isinstance(data, dict) and "results" in data else data
        if any(h.get("url") == url for h in hooks):
            return
        resp = requests.post(
            self._url("/api/webhooks"),
            headers=self.headers,
            json={"url": url, "project": project_id},
        )
        resp.raise_for_status()

    def check_connection(self) -> bool:
        resp = requests.get(self._url("/api/projects"), headers=self.headers)
        return resp.ok

    def has_webhook(self, url: str) -> bool:
        resp = requests.get(self._url("/api/webhooks"), headers=self.headers)
        resp.raise_for_status()
        data = resp.json()
        hooks = data["results"] if isinstance(data, dict) and "results" in data else data
        return any(h.get("url") == url for h in hooks)


__all__ = ["LabelStudioClient"]
