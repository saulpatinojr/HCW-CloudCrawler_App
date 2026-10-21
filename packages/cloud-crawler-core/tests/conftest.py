from __future__ import annotations

import json
from datetime import datetime

import pytest
from cloud_crawler_core.models import DecisionRecord
from core_fixtures import NOW, SAMPLES, make_decision


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def sample_export() -> dict:
    return json.loads((SAMPLES / "sample-resource-graph.json").read_text(encoding="utf-8"))


@pytest.fixture
def decision() -> DecisionRecord:
    return make_decision()
