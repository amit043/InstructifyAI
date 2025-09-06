import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "ui" / "curation-lite"


def test_package_json_next_dependencies():
    pkg_path = ROOT / "package.json"
    assert pkg_path.exists(), "package.json missing"
    pkg = json.loads(pkg_path.read_text())
    deps = pkg.get("dependencies", {})
    assert "next" in deps and "react" in deps and "react-dom" in deps


def test_core_files_present():
    for rel in [
        "pages/index.tsx",
        "components/ChunkList.tsx",
        "hooks/useHotkeys.ts",
        "hooks/useUndo.ts",
    ]:
        assert (ROOT / rel).exists(), f"{rel} missing"
