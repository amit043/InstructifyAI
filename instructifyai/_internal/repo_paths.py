from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Union


def _git_repo_root() -> Path | None:
    """Best-effort resolution of the git repo root."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        root = result.stdout.strip()
        return Path(root) if root else None
    except Exception:
        return None


def get_repo_root() -> Path:
    """Locate the repository root even when executed from notebooks/."""
    git_root = _git_repo_root()
    if git_root:
        return git_root
    cwd = Path.cwd()
    if cwd.name.lower() == "notebooks":
        return cwd.parent
    return cwd


def repo_script(relative_path: Union[str, Path]) -> Path:
    """Resolve a path under the repo root."""
    rel = Path(relative_path)
    return (get_repo_root() / rel).resolve()
