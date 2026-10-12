# tests/test_pipeline_alerts.py
import logging

from taxi_pipeline.alerts import notify_failure


class FakeTaskInstance:
    dag_id = "taxi_month_pipeline"
    task_id = "clean_month"
    run_id = "manual__2024-01-01"
    try_number = 3


def test_alert_logs_the_task_and_the_error(caplog):
    with caplog.at_level(logging.ERROR, logger="airflow.task"):
        notify_failure({"task_instance": FakeTaskInstance(), "exception": RuntimeError("boom")})
    assert "PIPELINE ALERT" in caplog.text
    assert "clean_month" in caplog.text
    assert "boom" in caplog.text


def test_alert_never_raises_even_with_an_empty_context():
    notify_failure({})
