from __future__ import annotations

from datetime import timedelta

import pytest
from cloud_crawler_core.hashing import sha256_of
from cloud_crawler_core.ingest import UNAUTHENTICATED_CAP, confidence_for, ingest, resources_of
from cloud_crawler_core.models import EvidenceClass, EvidenceKind, ScopeKind, SourceProvenance, SourceType, Subject
from cloud_crawler_core.normalize import IngestionError


def upload() -> SourceProvenance:
    return SourceProvenance(sourceType=SourceType.UPLOAD, artifactName="sample-resource-graph.json")


def test_arg_export_is_hashed_redacted_normalised_and_correlated(sample_export, now):
    sample_export["data"][0]["properties"]["primaryKey"] = "A" * 40
    record = ingest(
        kind=EvidenceKind.ARG_EXPORT,
        evidence_class=EvidenceClass.IMPORTED,
        payload=sample_export,
        subject=Subject(scope=ScopeKind.SUBSCRIPTION),
        provenance=upload(),
        authenticated=False,
        now=now,
    )
    assert record.payloadHash == sha256_of(sample_export)  # raw payload, before redaction
    assert record.redaction.removedCount == 1
    assert record.evidenceClass is EvidenceClass.IMPORTED
    assert record.confidence == UNAUTHENTICATED_CAP
    assert record.expiresAt == now + timedelta(days=7)
    assert len(record.correlations) == sample_export["count"]
    assert record.subject.subscriptionId == "00000000-0000-0000-0000-000000000001"
    assert len(record.subject.resourceIds) == sample_export["count"]
    assert len(resources_of(record)) == sample_export["count"]
    assert record.evidenceId.startswith("ev_")


def test_pipeline_imports_keep_their_confidence_when_authenticated(sample_export, now):
    record = ingest(
        kind=EvidenceKind.ARG_EXPORT,
        evidence_class=EvidenceClass.IMPORTED,
        payload=sample_export,
        subject=Subject(scope=ScopeKind.SUBSCRIPTION),
        provenance=SourceProvenance(sourceType=SourceType.PIPELINE, workflowRunId="1"),
        authenticated=True,
        now=now,
    )
    assert record.confidence == 0.90


def test_azure_mcp_results_are_stored_unparsed(now):
    payload = {"results": [{"name": "rec-1"}], "message": "ok"}
    record = ingest(
        kind=EvidenceKind.AZURE_MCP_RESULT,
        evidence_class=EvidenceClass.OBSERVED,
        payload=payload,
        subject=Subject(scope=ScopeKind.SUBSCRIPTION, subscriptionId="00000000-0000-0000-0000-000000000001"),
        provenance=SourceProvenance(
            sourceType=SourceType.AZURE_MCP, tool="advisor_recommendation_list", serverVersion="3.0.0"
        ),
        authenticated=True,
        now=now,
        ttl_override=timedelta(hours=1),
    )
    assert record.payload == payload
    assert record.correlations == [] and resources_of(record) == []
    assert record.confidence == 0.95 and record.expiresAt == now + timedelta(hours=1)


def test_class_must_suit_kind(sample_export):
    with pytest.raises(IngestionError) as exc:
        ingest(
            kind=EvidenceKind.ARG_EXPORT,
            evidence_class=EvidenceClass.OBSERVED,
            payload=sample_export,
            subject=Subject(scope=ScopeKind.SUBSCRIPTION),
            provenance=upload(),
            authenticated=False,
        )
    assert exc.value.code == "invalid_request"


def test_row_limit_and_shape_errors_propagate():
    with pytest.raises(IngestionError):
        ingest(
            kind=EvidenceKind.ARG_EXPORT,
            evidence_class=EvidenceClass.IMPORTED,
            payload=[{"id": "/a", "type": "t", "name": "n"}] * 3,
            subject=Subject(scope=ScopeKind.SUBSCRIPTION),
            provenance=upload(),
            authenticated=False,
            max_rows=2,
        )


def test_confidence_table_defaults():
    assert confidence_for(EvidenceClass.DERIVED, SourceType.HUMAN, authenticated=True) == (0.60, timedelta(hours=24))
    assert confidence_for(EvidenceClass.DECLARED, SourceType.HUMAN, authenticated=False)[0] == UNAUTHENTICATED_CAP
