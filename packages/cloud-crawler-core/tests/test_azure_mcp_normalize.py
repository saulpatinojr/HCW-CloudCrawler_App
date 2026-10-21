"""Azure MCP 3.0.0 result shapes -> observation rows, and their ingestion as observed evidence."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from cloud_crawler_core.ingest import ingest, observations_of, resources_of
from cloud_crawler_core.models import EvidenceClass, EvidenceKind, ScopeKind, SourceProvenance, SourceType, Subject
from cloud_crawler_core.normalize import IngestionError, parse_azure_mcp_result
from core_fixtures import NOW, SAMPLES

RECORDINGS = SAMPLES / "azure-mcp"


def recording(name: str) -> dict:
    return json.loads((RECORDINGS / f"{name}.json").read_text(encoding="utf-8"))


def provenance(tool: str) -> SourceProvenance:
    return SourceProvenance(sourceType=SourceType.AZURE_MCP, tool=tool, serverVersion="3.0.0")


@pytest.mark.parametrize(
    ("name", "tool", "count"),
    [
        ("subscription_list", "subscription_list", 1),
        ("group_list", "group_list", 2),
        ("advisor_recommendation_list", "advisor_recommendation_list", 2),
        ("advisor_recommendation_list.retirement", "advisor_recommendation_list", 1),
        ("policy_assignment_list", "policy_assignment_list", 1),
    ],
)
def test_every_recording_normalises(name, tool, count):
    parsed = parse_azure_mcp_result(tool, recording(name)["structuredContent"], max_rows=100)
    assert parsed is not None and parsed["tool"] == tool and len(parsed["rows"]) == count
    assert parsed["truncated"] is False


def test_advisor_rows_carry_resource_scope_and_retirement_fields():
    parsed = parse_azure_mcp_result(
        "advisor_recommendation_list",
        recording("advisor_recommendation_list.retirement")["structuredContent"],
        max_rows=10,
    )
    [row] = parsed["rows"]
    assert row["resourceId"].endswith("/microsoft.cache/redis/hcw-sample-redis-01")
    assert (
        row["subscriptionId"] == "00000000-0000-0000-0000-000000000001" and row["resourceGroup"] == "rg-hcw-sample-prod"
    )
    assert row["impactedField"] == "microsoft.cache/redis" and row["status"] == "New"
    assert row["subCategory"] == "ServiceUpgradeAndRetirement" and row["retirementDate"] == "2027-03-31"
    assert row["solution"].startswith("Migrate")
    dismissed = parse_azure_mcp_result(
        "advisor_recommendation_list", recording("advisor_recommendation_list")["structuredContent"], max_rows=10
    )["rows"][1]
    assert dismissed["status"] == "Dismissed" and dismissed["dismissReason"].startswith("Risk accepted")


def test_policy_rows_lower_case_ids_and_scope():
    [row] = parse_azure_mcp_result(
        "policy_assignment_list", recording("policy_assignment_list")["structuredContent"], max_rows=10
    )["rows"]
    assert (
        row["policyDefinitionId"]
        == "/providers/microsoft.authorization/policysetdefinitions/00000000-0000-0000-0000-000000000031"
    )
    assert row["scope"] == "/subscriptions/00000000-0000-0000-0000-000000000001" and row["enforcementMode"] == "Default"
    assert row["subscriptionId"] == "00000000-0000-0000-0000-000000000001"


def test_unknown_tool_or_shape_is_stored_unparsed():
    assert parse_azure_mcp_result(None, {"groups": []}, max_rows=10) is None
    assert parse_azure_mcp_result("pricing_get", {"items": []}, max_rows=10) is None
    assert parse_azure_mcp_result("group_list", {"results": []}, max_rows=10) is None
    assert parse_azure_mcp_result("group_list", "text", max_rows=10) is None


@pytest.mark.parametrize(
    ("tool", "payload"),
    [
        ("subscription_list", {"subscriptions": [{"displayName": "x"}]}),
        ("group_list", {"groups": [{"name": "x"}]}),
        ("advisor_recommendation_list", {"recommendations": ["x"]}),
        ("policy_assignment_list", {"assignments": [{"name": "x"}]}),
    ],
)
def test_rows_without_ids_are_rejected(tool, payload):
    with pytest.raises(IngestionError):
        parse_azure_mcp_result(tool, payload, max_rows=10)


def test_row_limit_applies():
    with pytest.raises(IngestionError, match="too_many_rows|more than"):
        parse_azure_mcp_result("group_list", {"groups": [{"id": "/a", "name": "a"}] * 3}, max_rows=2)


def test_ingest_normalises_a_known_tool_result():
    record = ingest(
        kind=EvidenceKind.AZURE_MCP_RESULT,
        evidence_class=EvidenceClass.OBSERVED,
        payload=recording("advisor_recommendation_list")["structuredContent"],
        subject=Subject(scope=ScopeKind.SUBSCRIPTION, subscriptionId="00000000-0000-0000-0000-000000000001"),
        provenance=provenance("advisor_recommendation_list"),
        authenticated=True,
        now=NOW,
    )
    tool, rows = observations_of(record)
    assert tool == "advisor_recommendation_list" and len(rows) == 2
    assert [c.value for c in record.correlations] == [r["resourceId"] for r in rows]
    assert resources_of(record) == []
    assert record.confidence == 0.95 and record.expiresAt == NOW + timedelta(hours=24)
    assert record.payloadHash.startswith("sha256:")


def test_observations_of_ignores_other_kinds_and_unparsed_results():
    record = ingest(
        kind=EvidenceKind.AZURE_MCP_RESULT,
        evidence_class=EvidenceClass.OBSERVED,
        payload={"results": [{"name": "rec-1"}]},
        subject=Subject(scope=ScopeKind.SUBSCRIPTION),
        provenance=provenance("advisor_recommendation_list"),
        authenticated=True,
        now=NOW,
    )
    assert observations_of(record) is None and record.payload == {"results": [{"name": "rec-1"}]}
