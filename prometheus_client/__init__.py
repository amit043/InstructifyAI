from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Dict, Iterable

CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"


class _BaseMetric:
    def __init__(
        self, name: str, documentation: str, labelnames: Iterable[str] | None = None
    ):
        self.name = name
        self.documentation = documentation
        self.value = 0.0
        _REGISTRY[name] = self

    def labels(self, *args, **_kwargs):
        return self


class Histogram(_BaseMetric):
    def observe(self, value: float) -> None:
        self.value = value

    @contextmanager
    def time(self):
        start = time.time()
        yield
        self.observe(time.time() - start)


class Gauge(_BaseMetric):
    def set(self, value: float) -> None:
        self.value = value


class Counter(_BaseMetric):
    def inc(self, amount: float = 1.0) -> None:
        self.value += amount


_REGISTRY: Dict[str, _BaseMetric] = {}


def generate_latest() -> bytes:
    lines = []
    for metric in _REGISTRY.values():
        lines.append(f"# HELP {metric.name} {metric.documentation}")
        lines.append(f"# TYPE {metric.name} gauge")
        lines.append(f"{metric.name} {metric.value}")
    return ("\n".join(lines) + "\n").encode("utf-8")


__all__ = [
    "Histogram",
    "Gauge",
    "Counter",
    "generate_latest",
    "CONTENT_TYPE_LATEST",
]
