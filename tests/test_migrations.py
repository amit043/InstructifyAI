import os
import subprocess
from pathlib import Path


def test_alembic_upgrade_and_downgrade(tmp_path: Path) -> None:
    db_file = tmp_path / "test.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_file}"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env.setdefault("MINIO_ENDPOINT", "localhost:9000")
    env.setdefault("MINIO_ACCESS_KEY", "test")
    env.setdefault("MINIO_SECRET_KEY", "test")
    env.setdefault("S3_BUCKET", "test")
    subprocess.check_call(["alembic", "upgrade", "head"], env=env)
    assert db_file.exists()
    subprocess.check_call(["alembic", "downgrade", "base"], env=env)
