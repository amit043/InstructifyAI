import os
import subprocess
from pathlib import Path


def test_alembic_upgrade_and_downgrade(tmp_path: Path) -> None:
    db_file = tmp_path / "test.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_file}"
    subprocess.check_call(["alembic", "upgrade", "head"], env=env)
    assert db_file.exists()
    subprocess.check_call(["alembic", "downgrade", "base"], env=env)
