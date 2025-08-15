from worker.suggestors import suggest


def test_rule_suggestors() -> None:
    text = "Step 1: start process ERROR in INC-1234 on 2024-01-01"
    result = suggest(text)
    step = result["step_id"]["value"]
    assert isinstance(step, str) and step.startswith("Step 1")
    assert result["severity"]["value"] == "ERROR"
    assert result["ticket_id"]["value"] == "INC-1234"
    assert result["datetime"]["value"] == "2024-01-01"


def test_suggestor_toggle_and_limit() -> None:
    text = "Step 1: start process ERROR in INC-1234 on 2024-01-01"
    assert suggest(text, use_rules_suggestor=False) == {}
    limited = suggest(text, max_suggestions=1)
    assert len(limited) == 1
