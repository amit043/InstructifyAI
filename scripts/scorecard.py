"""Run quality gates on the golden example set.

This CLI parses documents under ``examples/golden`` and computes
parse metrics for each file. It prints the metrics alongside the
configured thresholds and exits with a non-zero status code if any
file fails the gates.
"""

from __future__ import annotations

import argparse
import mimetypes
import sys
from pathlib import Path
from typing import Iterable

sys.path.append(str(Path(__file__).resolve().parents[1]))

from chunking.chunker import Chunk, chunk_blocks
from core.metrics import compute_parse_metrics
from parsers import registry

EMPTY_CHUNK_RATIO_THRESHOLD = 0.10
HTML_SECTION_PATH_COVERAGE_THRESHOLD = 0.90


def _parse_file(path: Path) -> tuple[list[Chunk], str]:
    mime, _ = mimetypes.guess_type(path)
    if mime is None:
        raise ValueError(f"Cannot determine MIME type for {path}")
    parser_cls = registry.get(mime)
    data = path.read_bytes()
    blocks = parser_cls.parse(data)
    chunks = chunk_blocks(blocks)
    return chunks, mime


def run(dir_path: Path) -> bool:
    """Parse all supported files under ``dir_path`` and enforce thresholds."""
    ok = True
    files: Iterable[Path] = sorted(dir_path.glob("*"))
    print(
        f"Thresholds: empty_chunk_ratio<={EMPTY_CHUNK_RATIO_THRESHOLD:.2f}, "
        f"html_section_path_coverage>={HTML_SECTION_PATH_COVERAGE_THRESHOLD:.2f}"
    )
    for file in files:
        if not file.is_file():
            continue
        try:
            chunks, mime = _parse_file(file)
        except ValueError:
            continue
        metrics = compute_parse_metrics(chunks, mime=mime)
        ecr = metrics.get("empty_chunk_ratio", 0.0)
        hsc = metrics.get("html_section_path_coverage", 0.0)
        print(
            f"{file.name}: empty_chunk_ratio={ecr:.2f}, html_section_path_coverage={hsc:.2f}"
        )
        if ecr > EMPTY_CHUNK_RATIO_THRESHOLD:
            print(
                f"  FAIL empty_chunk_ratio {ecr:.2f} > {EMPTY_CHUNK_RATIO_THRESHOLD:.2f}"
            )
            ok = False
        if mime == "text/html" and hsc < HTML_SECTION_PATH_COVERAGE_THRESHOLD:
            print(
                "  FAIL html_section_path_coverage "
                f"{hsc:.2f} < {HTML_SECTION_PATH_COVERAGE_THRESHOLD:.2f}"
            )
            ok = False
    if ok:
        print("scorecard passed")
    else:
        print("scorecard failed")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Run scorecard checks")
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("examples/golden"),
        help="Directory containing golden example documents",
    )
    args = parser.parse_args()
    ok = run(args.path)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
