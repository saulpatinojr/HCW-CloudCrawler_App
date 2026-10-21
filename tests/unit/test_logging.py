from __future__ import annotations

import json

import pytest
from cloud_crawler_core.redaction import VisitorDataError

from cloud_crawler_appliance.security import logging as logs


def test_log_event_writes_json_lines(capsys):
    logs.configure(silent=False)
    logs.log_event("startup", detectors=1, ok=True)
    line = json.loads(capsys.readouterr().err.strip())
    assert line["event"] == "startup" and line["detectors"] == 1 and "ts" in line


def test_log_event_refuses_text(capsys):
    logs.configure(silent=False)
    with pytest.raises(VisitorDataError):
        logs.log_event("startup", name="hcw-sample-sql-01")
    assert capsys.readouterr().err == ""


def test_log_exception_names_class_and_scrubs_message(capsys):
    logs.configure(silent=False)
    logs.log_exception(
        "unhandled_error", ValueError("/subscriptions/00000000-0000-0000-0000-000000000001 broke"), message=True
    )
    line = json.loads(capsys.readouterr().err.strip())
    assert line["exception"] == "ValueError" and "0000000" not in line["scrubbed"] and line["error"] is True


def test_silent_writes_nothing(capsys):
    logs.configure(silent=True)
    logs.log_event("shutdown")
    assert capsys.readouterr().err == ""
    logs.configure(silent=False)


def test_exception_field_must_be_identifier():
    logs.configure(silent=True)
    with pytest.raises(VisitorDataError):
        logs._write({"event": "startup", "exception": "not an identifier"})
    logs.configure(silent=False)
