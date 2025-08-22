from ops.metrics import (
    curation_completeness,
    dedupe_drop_percent,
    gate_failures,
    ocr_hit_ratio,
    stage_latency,
)


def test_metrics_endpoint(test_app) -> None:
    client, *_ = test_app
    stage_latency.labels(stage="test").observe(0.1)
    ocr_hit_ratio.set(0.5)
    dedupe_drop_percent.set(25.0)
    curation_completeness.set(0.8)
    gate_failures.labels("empty_chunk_ratio").inc()
    resp = client.get("/metrics")
    data = resp.text
    assert "stage_latency_seconds" in data
    assert "ocr_hit_ratio" in data
    assert "dedupe_drop_percent" in data
    assert "curation_completeness" in data
    assert "gate_failures_total" in data
