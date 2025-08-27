import requests  # type: ignore[import-untyped]

from integrations.label_studio_client import LabelStudioClient


class FakeResponse:
    def __init__(self, data, status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("error")


def test_upsert_project_creates(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def fake_get(url, params=None, headers=None):
        calls.append(("GET", url, params))
        return FakeResponse([])

    def fake_post(url, json=None, headers=None):
        calls.append(("POST", url, json))
        return FakeResponse({"id": 1, "slug": "s"})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)

    client = LabelStudioClient("http://ls", "t")
    proj = client.upsert_project("s", title="S")
    assert proj["id"] == 1
    assert calls[0] == ("GET", "http://ls/api/projects", {"slug": "s"})
    assert calls[1] == ("POST", "http://ls/api/projects", {"title": "S", "slug": "s"})


def test_create_tasks_batches(monkeypatch):
    posts: list[tuple[str, list]] = []

    def fake_post(url, json=None, headers=None):
        posts.append((url, json))
        return FakeResponse({})

    monkeypatch.setattr(requests, "post", fake_post)

    client = LabelStudioClient("http://ls", "t")
    tasks = [{"id": i} for i in range(3)]
    client.create_tasks(5, tasks, batch_size=2)
    assert posts[0][0] == "http://ls/api/projects/5/tasks/bulk"
    assert len(posts[0][1]) == 2
    assert len(posts[1][1]) == 1


def test_ensure_webhook(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_get(url, params=None, headers=None):
        return FakeResponse({"results": []})

    def fake_post(url, json=None, headers=None):
        calls.append((url, json["url"]))
        return FakeResponse({})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)

    client = LabelStudioClient("http://ls", "t")
    client.ensure_webhook(3, "http://webhook")
    assert calls[0] == ("http://ls/api/webhooks", "http://webhook")
