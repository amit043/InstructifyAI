from __future__ import annotations

from core.notify import get_notifier


def notify_ingest_done(project_id: str, artifact_url: str) -> None:
    get_notifier().notify(project_id, "ingest_done", artifact_url)


def notify_export_ready(project_id: str, artifact_url: str) -> None:
    get_notifier().notify(project_id, "export_ready", artifact_url)


def notify_release_created(project_id: str, artifact_url: str) -> None:
    get_notifier().notify(project_id, "release_created", artifact_url)
