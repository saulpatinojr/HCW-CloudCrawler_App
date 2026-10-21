from __future__ import annotations

from datetime import timedelta

import pytest
from cloud_crawler_core.drift import evaluate_decision
from cloud_crawler_core.ids import new_id
from cloud_crawler_core.ingest import ingest
from cloud_crawler_core.ledger import InMemoryLedger, NotFound
from cloud_crawler_core.models import (
    Approval,
    ApprovalDecision,
    EvidenceClass,
    EvidenceKind,
    ScopeKind,
    SourceProvenance,
    SourceType,
    Subject,
)
from cloud_crawler_core.report import NOT_AN_AUDIT, bundle


def test_ledger_round_trip_and_contradiction_merge(decision, sample_export, now):
    ledger = InMemoryLedger()
    ledger.add_decision(decision)
    assert ledger.get_decision(decision.decisionId) is decision
    with pytest.raises(NotFound):
        ledger.get_decision("dec_missing")
    record = ingest(
        kind=EvidenceKind.ARG_EXPORT,
        evidence_class=EvidenceClass.IMPORTED,
        payload=sample_export,
        subject=Subject(scope=ScopeKind.SUBSCRIPTION),
        provenance=SourceProvenance(sourceType=SourceType.UPLOAD),
        authenticated=False,
        now=now,
    )
    ledger.add_evidence(record)
    assert ledger.get_evidence(record.evidenceId) is record
    with pytest.raises(NotFound):
        ledger.get_evidence("ev_missing")
    first = ledger.record(evaluate_decision(decision, ledger.evidence_for(decision, now=now), now=now))
    later = now + timedelta(hours=1)
    second = ledger.record(evaluate_decision(decision, ledger.evidence_for(decision, now=later), now=later))
    assert {c.contradictionId for c in first.contradictions} == {c.contradictionId for c in second.contradictions}
    assert all(c.firstSeenAt == now and c.lastSeenAt == later for c in second.contradictions)
    assert len(ledger.open_contradictions(decision.decisionId)) == 2
    assert len(ledger.findings_for(decision.decisionId)) == len(first.findings) + len(second.findings)
    assert len(ledger.open_proposals()) == 2  # one per evaluation; proposal lifecycle comes with review_decide
    assert ledger.evidence_for(decision, now=now + timedelta(days=8)) == []
    approval = Approval(
        approvalId=new_id("approval"),
        proposalId=first.proposals[0].proposalId,
        decision=ApprovalDecision.APPROVE,
        actorId="sha256:x",
        at=later,
        evidenceSnapshotHash="sha256:y",
    )
    assert ledger.add_approval(approval) is approval


def test_bundle_contents(decision, sample_export, now):
    record = ingest(
        kind=EvidenceKind.ARG_EXPORT,
        evidence_class=EvidenceClass.IMPORTED,
        payload=sample_export,
        subject=Subject(scope=ScopeKind.SUBSCRIPTION),
        provenance=SourceProvenance(sourceType=SourceType.UPLOAD),
        authenticated=False,
        now=now,
    )
    result = evaluate_decision(decision, [record], now=now)
    files = bundle(decision, result)
    assert set(files) == {"report.md", "report.json", "NOT-AN-AUDIT.md"}
    assert files["NOT-AN-AUDIT.md"] == NOT_AN_AUDIT
    assert "| contradicted |" in files["report.md"] and "hcw-sample-sql-01" in files["report.md"]
    assert "Claim contradicted" in files["report.md"]
    assert '"engine"' in files["report.json"] and decision.decisionId in files["report.json"]
    empty = bundle(decision, evaluate_decision(decision, [], now=now))
    assert "n/a" in empty["report.md"] and "Review proposals" not in empty["report.md"]
