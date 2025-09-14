from __future__ import annotations

"""Label Studio bootstrap client: create or update project, set config, webhook."""

from typing import Any

import requests  # type: ignore[import-untyped]


class LabelStudioClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Token {token}"}

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _find_project_by_name(self, name: str) -> dict | None:
        resp = requests.get(self._url("/api/projects"), headers=self.headers)
        resp.raise_for_status()
        data = resp.json()
        projects = data.get("results") if isinstance(data, dict) else data
        for proj in projects:
            if proj.get("title") == name or proj.get("name") == name:
                return proj
        return None

    def _create_project(self, name: str) -> dict:
        payload = {"title": name}
        resp = requests.post(
            self._url("/api/projects"), headers=self.headers, json=payload
        )
        resp.raise_for_status()
        return resp.json()

    def _update_project_config(self, project_id: int, xml: str) -> None:
        resp = requests.patch(
            self._url(f"/api/projects/{project_id}"),
            headers=self.headers,
            json={"label_config": xml},
        )
        resp.raise_for_status()

    def _ensure_webhook(self, project_id: int, url: str) -> None:
        resp = requests.get(
            self._url("/api/webhooks"),
            headers=self.headers,
            params={"project": project_id},
        )
        resp.raise_for_status()
        data = resp.json()
        hooks = data.get("results") if isinstance(data, dict) else data
        if any(h.get("url") == url for h in hooks):
            return
        resp = requests.post(
            self._url("/api/webhooks"),
            headers=self.headers,
            json={"url": url, "project": project_id},
        )
        resp.raise_for_status()

    def create_or_update_project(self, name: str, xml: str, webhook_url: str) -> dict:
        """Ensure a project exists with given name, config, and webhook.

        Returns the project JSON.
        """
        proj = self._find_project_by_name(name)
        if proj is None:
            proj = self._create_project(name)
        pid = int(proj["id"])
        self._update_project_config(pid, xml)
        self._ensure_webhook(pid, webhook_url)
        return proj


__all__ = ["LabelStudioClient"]

