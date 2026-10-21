from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


@pytest.fixture
def sample_export() -> dict:
    return json.loads((SAMPLES / "sample-resource-graph.json").read_text(encoding="utf-8"))


@pytest.fixture
def sample_decision() -> dict:
    return json.loads((SAMPLES / "decision-zone-redundancy.json").read_text(encoding="utf-8"))


@pytest.fixture
def quiet_env() -> dict[str, str]:
    return {"CC_LOG_SILENT": "1", "CC_ALLOWED_HOSTS": "testserver 127.0.0.1:* localhost:*"}
