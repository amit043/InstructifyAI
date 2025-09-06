import subprocess


def test_scorecard_e2e():
    subprocess.run(["python", "scripts/generate_bundles.py"], check=True)
    result = subprocess.run(
        ["python", "scripts/scorecard.py", "--path", "examples/bundles"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "scorecard passed" in result.stdout
