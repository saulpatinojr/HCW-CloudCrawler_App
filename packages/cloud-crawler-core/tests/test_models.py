from __future__ import annotations

import pytest
from cloud_crawler_core.ids import new_id
from cloud_crawler_core.models import DecisionRecord, Evidence, Verdict
from pydantic import ValidationError


def test_ids_are_prefixed_and_time_ordered():
    a, b = new_id("evidence"), new_id("evidence")
    assert a.startswith("ev_") and b.startswith("ev_") and a < b
    with pytest.raises(KeyError):
        new_id("thing")


def test_decision_round_trips_through_json(decision):
    data = decision.model_dump(mode="json", by_alias=True)
    assert DecisionRecord.model_validate(data) == decision


def test_unknown_fields_are_rejected(decision):
    data = decision.model_dump(mode="json", by_alias=True)
    data["extra"] = 1
    with pytest.raises(ValidationError):
        DecisionRecord.model_validate(data)


def test_evidence_class_uses_the_json_name_class():
    with pytest.raises(ValidationError):
        Evidence.model_validate({"evidenceId": "ev_x"})
    assert Verdict("not-applicable") is Verdict.NOT_APPLICABLE
