from core.guidelines import GuidelineUsage, log_guideline_usage


def test_log_guideline_usage(caplog):
    event = GuidelineUsage(user="tester", action="view", field="severity")
    with caplog.at_level("INFO"):
        log_guideline_usage(event)
    record = caplog.records[0]
    assert record.user == "tester"
    assert record.action == "view"
    assert record.field == "severity"
