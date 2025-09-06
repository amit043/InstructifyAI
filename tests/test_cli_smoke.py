from pathlib import Path

from typer.testing import CliRunner  # type: ignore[import-not-found]

from scripts import instructify_cli


def test_cli_commands(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    calls = {}

    def fake_post(url, params=None, files=None, json=None):
        calls["url"] = url
        calls["params"] = params
        calls["files"] = files
        calls["json"] = json

        class Resp:
            def json(self) -> dict[str, str]:
                return {"ok": "post"}

        return Resp()

    def fake_get(url, params=None):
        calls["url"] = url
        calls["params"] = params

        class Resp:
            def json(self) -> dict[str, str]:
                return {"ok": "get"}

        return Resp()

    monkeypatch.setattr(instructify_cli.requests, "post", fake_post)
    monkeypatch.setattr(instructify_cli.requests, "get", fake_get)

    file = tmp_path / "doc.txt"
    file.write_text("hello")
    result = runner.invoke(instructify_cli.app, ["ingest", "proj", str(file)])
    assert result.exit_code == 0
    assert calls["url"].endswith("/ingest")

    result = runner.invoke(instructify_cli.app, ["reparse", "doc1"])
    assert result.exit_code == 0
    assert calls["url"].endswith("/documents/doc1/reparse")

    result = runner.invoke(instructify_cli.app, ["export", "doc1", "csv"])
    assert result.exit_code == 0
    assert calls["url"].endswith("/export/csv")

    result = runner.invoke(instructify_cli.app, ["release", "create", "proj"])
    assert result.exit_code == 0
    assert calls["url"].endswith("/projects/proj/releases")

    result = runner.invoke(instructify_cli.app, ["release", "diff", "r1", "r2"])
    assert result.exit_code == 0
    assert calls["url"].endswith("/releases/diff")
    assert calls["params"] == {"base": "r1", "compare": "r2"}

    def fake_run(path: Path) -> bool:
        calls["path"] = path
        return True

    monkeypatch.setattr(instructify_cli.scorecard, "run", fake_run)
    result = runner.invoke(instructify_cli.app, ["scorecard", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert calls["path"] == tmp_path
