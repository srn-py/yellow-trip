# tests/test_logging_config.py
import json
import logging

import pytest

from shared.logging_config import JsonFormatter, request_id_var, setup_logging


@pytest.fixture
def clean_root_logger():
    """Put the root logger back exactly as it was after the test."""
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    yield
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


def make_record(**extra) -> logging.LogRecord:
    record = logging.LogRecord("app.module", logging.INFO, __file__, 10, "loaded %d rows", (5,), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_line_has_the_core_fields_and_extras():
    data = json.loads(JsonFormatter("etl").format(make_record(request_id="abc123", month="2024-01")))
    assert data["service"] == "etl"
    assert data["level"] == "INFO"
    assert data["message"] == "loaded 5 rows"
    assert data["request_id"] == "abc123"
    assert data["month"] == "2024-01"
    assert "time" in data


def test_exceptions_are_included_as_text():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    data = json.loads(JsonFormatter("etl").format(record))
    assert "ValueError: boom" in data["exception"]


def test_json_mode_writes_one_json_object_per_line(capsys, clean_root_logger):
    setup_logging("svc", "INFO", "json")
    logging.getLogger("test").info("hello", extra={"rows": 3})
    line = capsys.readouterr().out.strip().splitlines()[-1]
    data = json.loads(line)
    assert data["message"] == "hello"
    assert data["rows"] == 3


def test_text_mode_shows_the_request_id(capsys, clean_root_logger):
    setup_logging("svc", "INFO", "text")
    token = request_id_var.set("req-42")
    try:
        logging.getLogger("test").info("hello")
    finally:
        request_id_var.reset(token)
    assert "req-42" in capsys.readouterr().out
