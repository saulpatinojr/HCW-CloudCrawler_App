"""Terraform documents through the ingestion pipeline (ticket #54): hash the raw document, redact, withhold what
Terraform marks sensitive, store the rows and a summary and never the document."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from cloud_crawler_core.drift import evaluate_decision
from cloud_crawler_core.hashing import sha256_of
from cloud_crawler_core.ingest import NORMALISED_KINDS, UNAUTHENTICATED_CAP, ingest, resources_of
from cloud_crawler_core.models import (
    DecisionScope,
    EvidenceClass,
    EvidenceKind,
    NormalizedResource,
    ScopeKind,
    SourceProvenance,
    SourceType,
    Subject,
    Verdict,
)
from cloud_crawler_core.normalize import IngestionError
from cloud_crawler_core.redaction import REDACTED, redact_payload
from core_fixtures import NOW, SAMPLES, make_decision
from terraform_fixtures import SUB, arm_id, change_entry, plan_of, state_of, state_record

STATE = json.loads((SAMPLES / "terraform" / "sample-estate.state.json").read_text(encoding="utf-8"))
PLAN = json.loads((SAMPLES / "terraform" / "sample-estate.plan.json").read_text(encoding="utf-8"))
SCOPE = Subject(scope=ScopeKind.SUBSCRIPTION, subscriptionId=SUB)
UPLOAD = SourceProvenance(sourceType=SourceType.UPLOAD, artifactName="sample-estate.state.json")


def take(kind: EvidenceKind, payload: Any, *, subject: Subject = SCOPE, **kwargs: Any):
    kwargs.setdefault("authenticated", False)
    kwargs.setdefault("provenance", UPLOAD)
    kwargs.setdefault("now", NOW)
    return ingest(kind=kind, evidence_class=EvidenceClass.IMPORTED, payload=payload, subject=subject, **kwargs)


def test_both_kinds_are_normalised_kinds():
    assert {EvidenceKind.TF_STATE, EvidenceKind.TF_PLAN} <= NORMALISED_KINDS


def test_a_state_is_hashed_as_it_arrived_and_stored_as_rows_and_a_summary():
    record = take(EvidenceKind.TF_STATE, STATE)
    assert record.payloadHash == sha256_of(STATE)  # the document as it arrived, secrets included
    assert record.evidenceClass is EvidenceClass.IMPORTED and record.kind is EvidenceKind.TF_STATE
    assert set(record.payload) == {"resources", "terraform"}
    assert len(record.payload["resources"]) == 13 and record.payload["terraform"]["mapped"] == 13
    assert len(resources_of(record)) == 13
    assert record.confidence == UNAUTHENTICATED_CAP and record.expiresAt == NOW + timedelta(days=7)
    assert record.subject.subscriptionId == SUB and len(record.subject.resourceIds) == 13
    assert {c.type for c in record.correlations} == {"resource"} and len(record.correlations) == 13


def test_an_upload_through_a_pipeline_keeps_the_confidence_of_an_import():
    record = take(
        EvidenceKind.TF_PLAN,
        PLAN,
        provenance=SourceProvenance(sourceType=SourceType.PIPELINE, workflowRunId="1"),
        authenticated=True,
    )
    assert record.confidence == 0.90 and record.evidenceClass is EvidenceClass.IMPORTED


def test_nothing_terraform_marked_sensitive_reaches_what_is_stored():
    stored = json.dumps(take(EvidenceKind.TF_STATE, STATE).payload) + json.dumps(
        take(EvidenceKind.TF_PLAN, PLAN).payload
    )
    assert "fictional-placeholder" not in stored and "sensitive_attributes" not in stored
    assert "fictional-private-blob" not in stored
    assert "kube_config" not in stored and "administrator" not in stored  # attributes nobody asked for are not copied


def test_a_secret_shaped_value_is_redacted_before_it_is_read_and_a_denied_key_loses_its_value():
    token_like = "ghp_" + "t" * 24  # built at run time so no token-shaped text sits in the source
    document = state_of(
        state_record(
            "azurerm_key_vault",
            "v",
            {"id": arm_id("A", "b", "c"), "name": "v", "tags": {"owner": token_like, "password": "hunter2"}},
        )
    )
    record = take(EvidenceKind.TF_STATE, document)
    [row] = resources_of(record)
    assert row.tags == {"owner": REDACTED, "password": REDACTED}
    assert record.redaction.removedCount == 2
    assert record.payloadHash == sha256_of(document)


def test_a_plan_is_stored_as_rows_and_the_ones_without_an_azure_id_are_correlated_by_address():
    record = take(EvidenceKind.TF_PLAN, PLAN)
    assert record.payload["terraform"]["withoutAzureId"] == 2 and len(record.payload["resources"]) == 15
    by_type = {t: [c.value for c in record.correlations if c.type == t] for t in {c.type for c in record.correlations}}
    assert sorted(by_type) == ["resource", "terraform-address"]
    assert len(by_type["resource"]) == 13
    assert by_type["terraform-address"] == [
        "terraform:azurerm_storage_account.logs",
        "terraform:azurerm_public_ip.new",
    ]
    assert (
        all(i.startswith("/subscriptions/") for i in record.subject.resourceIds)
        and len(record.subject.resourceIds) == 13
    )


def test_kinds_are_imported_evidence_only():
    for kind in (EvidenceKind.TF_STATE, EvidenceKind.TF_PLAN):
        with pytest.raises(IngestionError) as exc:
            ingest(
                kind=kind,
                evidence_class=EvidenceClass.OBSERVED,
                payload=STATE,
                subject=SCOPE,
                provenance=UPLOAD,
                authenticated=False,
            )
        assert exc.value.code == "invalid_request"


@pytest.mark.parametrize("kind", [EvidenceKind.TF_STATE, EvidenceKind.TF_PLAN])
def test_a_document_that_is_the_wrong_kind_of_terraform_is_refused(kind):
    wrong = PLAN if kind is EvidenceKind.TF_STATE else STATE
    with pytest.raises(IngestionError) as exc:
        take(kind, wrong)
    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize("kind", [EvidenceKind.TF_STATE, EvidenceKind.TF_PLAN])
@pytest.mark.parametrize("depth", [101, 50_000])
def test_a_deeply_nested_document_is_refused_before_hashing_or_redaction_can_overflow_the_stack(kind, depth):
    node: Any = 1
    for _ in range(depth):
        node = [node]
    if kind is EvidenceKind.TF_STATE:
        document = state_of(state_record("azurerm_key_vault", "v", {"id": "x", "deep": node}))
    else:
        document = plan_of(change_entry("azurerm_key_vault", "v", {"id": "x", "deep": node}))
    with pytest.raises(IngestionError) as exc:
        take(kind, document)
    assert exc.value.code == "too_large"


def test_the_row_limit_of_the_caller_applies():
    with pytest.raises(IngestionError) as exc:
        take(EvidenceKind.TF_STATE, STATE, max_rows=13)  # thirteen rows and the node pool that joins its cluster
    assert exc.value.code == "too_many_rows"
    assert len(take(EvidenceKind.TF_STATE, STATE, max_rows=14).payload["resources"]) == 13


def test_an_unreadable_document_leaves_the_ledger_with_nothing_half_made():
    broken = {"version": 4, "resources": [{"instances": [{"attributes": {"id": "x"}}]}, 5]}
    with pytest.raises(IngestionError):
        take(EvidenceKind.TF_STATE, broken)


# --- what the rows are worth to a decision ----------------------------------------------------------------------------


def storage_creation() -> dict[str, Any]:
    after = {
        "name": "hcwsamplestnew01",
        "account_tier": "Standard",
        "account_replication_type": "LRS",
        "tags": {"env": "prod"},
        "identity": [],
    }
    return plan_of(change_entry("azurerm_storage_account", "new", after, actions=("create",)))


def decide(evidence) -> Any:
    decision = make_decision(scope=DecisionScope(subscriptionIds=[SUB]))
    return evaluate_decision(decision, [evidence], now=NOW)


def test_a_resource_the_plan_creates_is_judged_when_the_caller_names_its_subscription():
    result = decide(take(EvidenceKind.TF_PLAN, storage_creation(), subject=SCOPE))
    verdicts = {f.resourceId: f.verdict for f in result.findings}
    assert verdicts == {"terraform:azurerm_storage_account.new": Verdict.CONTRADICTED}  # LRS where ZRS is required


def test_without_a_named_subscription_such_a_resource_is_outside_a_subscription_scoped_decision():
    result = decide(take(EvidenceKind.TF_PLAN, storage_creation(), subject=Subject(scope=ScopeKind.TENANT)))
    [finding] = result.findings
    assert finding.verdict is Verdict.UNKNOWN and "no usable evidence in scope" in finding.unknownReason


def test_the_rows_of_a_state_and_of_a_resource_graph_export_of_one_estate_agree_on_the_zone_question():
    from core_fixtures import SAMPLES as samples

    export = json.loads((samples / "sample-resource-graph.json").read_text(encoding="utf-8"))
    from_export = decide(
        ingest(
            kind=EvidenceKind.ARG_EXPORT,
            evidence_class=EvidenceClass.IMPORTED,
            payload=export,
            subject=SCOPE,
            provenance=UPLOAD,
            authenticated=False,
            now=NOW,
        )
    )
    from_state = decide(take(EvidenceKind.TF_STATE, STATE))
    as_pairs = lambda result: sorted((f.resourceId, f.verdict.value) for f in result.findings)  # noqa: E731
    assert as_pairs(from_export) == as_pairs(from_state)
    assert from_state.summary == from_export.summary


def test_a_row_round_trips_through_the_stored_payload():
    record = take(EvidenceKind.TF_STATE, STATE)
    again = [NormalizedResource.model_validate(row) for row in record.payload["resources"]]
    assert again == resources_of(record)


# --- a record stored before Terraform was normalised (CodeRabbit review of pull request 60) -------------------------


def legacy(kind: EvidenceKind, document: dict[str, Any]):
    """What an engine that stored these two kinds unread kept: the redacted document itself as the payload. Only an
    in-memory ledger that survived an engine upgrade could hold one; the model does not stop it being built."""
    return take(kind, document).model_copy(update={"payload": redact_payload(document)[0]})


@pytest.mark.parametrize(
    ("kind", "document"), [(EvidenceKind.TF_STATE, STATE), (EvidenceKind.TF_PLAN, PLAN)], ids=["state", "plan"]
)
def test_a_record_that_holds_the_unread_document_gives_no_rows_instead_of_a_validation_error(kind, document):
    record = legacy(kind, document)
    assert "terraform" not in record.payload
    assert resources_of(record) == []


def test_a_decision_over_a_ledger_holding_such_a_record_is_judged_on_the_other_records():
    old = legacy(EvidenceKind.TF_STATE, STATE)
    current = take(EvidenceKind.TF_STATE, STATE)
    decision = make_decision(scope=DecisionScope(subscriptionIds=[SUB]))
    alone = evaluate_decision(decision, [current], now=NOW)
    with_old = evaluate_decision(decision, [old, current], now=NOW)  # raised a validation error before
    assert [(f.claimId, f.resourceId, f.verdict) for f in with_old.findings] == [
        (f.claimId, f.resourceId, f.verdict) for f in alone.findings
    ]
    only_old = evaluate_decision(decision, [old], now=NOW)  # nothing readable: no rows, nothing invented
    assert not any(f.resourceId for f in only_old.findings)
