from __future__ import annotations

from functools import wraps
from typing import Callable, TypeVar

from prometheus_client import Counter, Gauge, Histogram

T = TypeVar("T")

stage_latency = Histogram(
    "stage_latency_seconds", "Latency for pipeline stages", ["stage"]
)
ocr_hit_ratio = Gauge("ocr_hit_ratio", "OCR hit ratio")
dedupe_drop_percent = Gauge(
    "dedupe_drop_percent", "Percentage of chunks dropped by dedupe"
)
curation_completeness = Gauge("curation_completeness", "Curation completeness ratio")
gate_failures = Counter("gate_failures_total", "Quality gate failures", ["gate"])


def timed_stage(stage: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs):
            with stage_latency.labels(stage=stage).time():
                return func(*args, **kwargs)

        return wrapper

    return decorator


__all__ = [
    "stage_latency",
    "ocr_hit_ratio",
    "dedupe_drop_percent",
    "curation_completeness",
    "gate_failures",
    "timed_stage",
]
