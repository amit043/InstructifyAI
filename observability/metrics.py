from __future__ import annotations

from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

# Core counters/gauges
INGEST_REQUESTS = Counter("ingest_requests_total", "Ingest requests")
PARSE_SUCCESS = Counter("parse_success_total", "Successful parses")
PARSE_FAILURE = Counter("parse_failure_total", "Failed parses")
OCR_PAGES = Counter("ocr_pages_total", "Pages OCR'ed")
OCR_FALLBACK_TOTAL = Counter(
    "ocr_fallback_total", "OCR fallback events", ["from", "to"]
)
JOB_QUEUE_LAG = Gauge("celery_queue_lag_seconds", "Approx queue lag")

# Example histograms/placeholders (extend as needed)
PARSE_DURATION = Histogram("parse_duration_seconds", "Parse duration seconds")


def metrics_endpoint() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


__all__ = [
    "INGEST_REQUESTS",
    "PARSE_SUCCESS",
    "PARSE_FAILURE",
    "OCR_PAGES",
    "OCR_FALLBACK_TOTAL",
    "JOB_QUEUE_LAG",
    "PARSE_DURATION",
    "metrics_endpoint",
]

