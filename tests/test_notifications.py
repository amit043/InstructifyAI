from __future__ import annotations

import json
from urllib import request

import pytest

from core.notify import get_notifier
from worker.notifications import (
    notify_export_ready,
    notify_ingest_done,
    notify_release_created,
)


@pytest.fixture(autouse=True)
def reset_notifier():
    notifier = get_notifier()
    notifier.project_hooks.clear()
    yield
    notifier.project_hooks.clear()


def test_sends_notification(monkeypatch):
    notifier = get_notifier()
    notifier.opt_in("p1", "http://hook")
    captured: dict[str, bytes] = {}

    def fake_urlopen(req, timeout=2):
        captured["data"] = req.data
        captured["url"] = req.full_url

    monkeypatch.setattr(request, "urlopen", fake_urlopen)
    notify_ingest_done("p1", "http://artifact")
    body = json.loads(captured["data"].decode())
    assert body["event"] == "ingest_done"
    assert body["artifact_url"] == "http://artifact"
    assert captured["url"] == "http://hook"


def test_no_notification_when_opted_out(monkeypatch):
    called = False

    def fake_urlopen(req, timeout=2):
        nonlocal called
        called = True

    monkeypatch.setattr(request, "urlopen", fake_urlopen)
    notify_export_ready("p2", "http://artifact")
    assert not called


def test_retries_with_backoff(monkeypatch):
    notifier = get_notifier()
    notifier.opt_in("p3", "http://hook")
    attempts = []

    def fake_urlopen(req, timeout=2):
        attempts.append(1)
        if len(attempts) < 3:
            raise OSError("boom")

    monkeypatch.setattr(request, "urlopen", fake_urlopen)
    sleeps: list[float] = []
    import core.notify as notify_module

    monkeypatch.setattr(notify_module.time, "sleep", lambda s: sleeps.append(s))
    notify_release_created("p3", "http://artifact")
    assert len(attempts) == 3
    assert sleeps == [0.5, 1.0]
