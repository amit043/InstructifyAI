"""Scorecard CLI to validate golden set metrics."""  # mypy: ignore-errors

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Tuple

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.metrics import compute_curation_completeness
from models import Base, DocumentVersion


def run(db_url: str, threshold: float) -> bool:
    """Run scorecard checks against all document versions.

    Returns True if all documents pass the threshold, otherwise False.
    """
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    failures: List[Tuple[str, float]] = []
    with Session(engine) as session:
        versions = session.scalars(select(DocumentVersion)).all()
        for dv in versions:
            completeness = compute_curation_completeness(
                dv.document_id, dv.project_id, dv.version, session
            )
            if completeness < threshold:
                failures.append((dv.document_id, completeness))
    if failures:
        for doc_id, comp in failures:
            print(f"{doc_id} completeness {comp:.2f} below {threshold}")
        return False
    print("scorecard passed")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Run scorecard checks")
    parser.add_argument("--db", default="sqlite:///scorecard.db")
    parser.add_argument("--threshold", type=float, default=0.8)
    args = parser.parse_args()
    ok = run(args.db, args.threshold)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
