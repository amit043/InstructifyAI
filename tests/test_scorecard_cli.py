from pathlib import Path

from scripts.scorecard import run


def test_scorecard_pass(tmp_path):
    good = tmp_path / "good.html"
    good.write_text("<html><body><h1>Title</h1><p>text</p></body></html>")
    assert run(tmp_path)


def test_scorecard_fail(tmp_path):
    bad = tmp_path / "bad.html"
    bad.write_text("<html><body>text</body></html>")
    assert not run(tmp_path)
