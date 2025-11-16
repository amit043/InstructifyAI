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
GEN_ASK_DURATION = Histogram("gen_ask_duration_seconds", "gen ask duration seconds")
ADAPTER_CACHE_EVENTS = Counter(
    "adapter_cache_events_total", "Adapter cache operations", ["event"]
)
GEN_WARM_DURATION = Histogram(
    "gen_warm_duration_seconds", "gen warm-up duration seconds"
)
GEN_WARM_EVENTS = Counter(
    "gen_warm_events_total", "gen warm-up events", ["status"]
)
GEN_EVIDENCE_RESULTS = Counter(
    "gen_evidence_results_total", "gen/ask evidence retrieval outcomes", ["result"]
)
GEN_VALIDATION_TOTAL = Counter(
    "gen_validation_total", "gen/ask validation outcomes", ["outcome"]
)


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
    "GEN_ASK_DURATION",
    "ADAPTER_CACHE_EVENTS",
    "GEN_WARM_DURATION",
    "GEN_WARM_EVENTS",
    "GEN_EVIDENCE_RESULTS",
    "GEN_VALIDATION_TOTAL",
    "metrics_endpoint",
]
