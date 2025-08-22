from __future__ import annotations

"""Pack rows into a HuggingFace ``DatasetDict`` tarball."""

import io
import os
import tarfile
import tempfile
from typing import Any, Dict, List


def pack_datasetdict(rows: List[Dict[str, Any]]) -> bytes:
    """Return a tar.gz of a ``DatasetDict`` with a single ``train`` split."""
    from datasets import Dataset, DatasetDict  # type: ignore[import-not-found]

    ds = Dataset.from_list(rows)
    dsd = DatasetDict({"train": ds})
    with tempfile.TemporaryDirectory() as tmp:
        dsd.save_to_disk(tmp)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(tmp, arcname="dataset")
        return buf.getvalue()


__all__ = ["pack_datasetdict"]
