from typing import Any, cast

from celery import chain, chord, group  # type: ignore[import-untyped]

from worker.tasks.chunk_write import chunk_write
from worker.tasks.extract import extract
from worker.tasks.finalize import finalize
from worker.tasks.normalize import normalize
from worker.tasks.ocr import ocr_page
from worker.tasks.preflight import preflight
from worker.tasks.structure import structure


def build_flow(
    doc_id: str,
    *,
    request_id: str | None = None,
    do_ocr: bool = False,
):
    """Build the Celery Canvas pipeline for parsing."""
    steps = [
        cast(Any, preflight).s(doc_id, request_id=request_id),
        cast(Any, normalize).s(request_id=request_id),
        cast(Any, extract).s(request_id=request_id),
    ]
    if do_ocr:
        ocr_group = group(
            cast(Any, ocr_page).s(doc_id, request_id=request_id).set(queue="ocr")
        )
        steps.append(chord(ocr_group, cast(Any, structure).s(request_id=request_id)))
    else:
        steps.append(cast(Any, structure).s(request_id=request_id))
    steps.extend(
        [
            cast(Any, chunk_write).s(request_id=request_id),
            cast(Any, finalize).s(request_id=request_id),
        ]
    )
    return chain(*steps)
