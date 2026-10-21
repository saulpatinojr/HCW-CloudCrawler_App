from __future__ import annotations

from datetime import timedelta

from cloud_crawler_core.drift import evaluate_decision, summarise
from cloud_crawler_core.ingest import ingest
from cloud_crawler_core.models import (
    DecisionScope,
    EvidenceClass,
    EvidenceKind,
    ProposalKind,
    ScopeKind,
    SourceProvenance,
    SourceType,
    Subject,
    Verdict,
)
from core_fixtures import make_decision


def imported(sample_export, now, **kwargs):
    return ingest(
        kind=EvidenceKind.ARG_EXPORT,
        evidence_class=EvidenceClass.IMPORTED,
        payload=sample_export,
        subject=Subject(scope=ScopeKind.SUBSCRIPTION),
        provenance=SourceProvenance(sourceType=SourceType.UPLOAD),
        authenticated=False,
        now=now,
        **kwargs,
    )


def by_name(result):
    return {f.resourceId.rsplit("/", 1)[-1]: f.verdict for f in result.findings if f.resourceId}


def test_sample_estate_verdicts(decision, sample_export, now):
    result = evaluate_decision(decision, [imported(sample_export, now)], now=now)
    verdicts = by_name(result)
    assert verdicts["hcw-sample-sql-01"] is Verdict.CONTRADICTED
    assert verdicts["hcw-sample-cosmos-prod-01"] is Verdict.CONTRADICTED
    assert verdicts["hcw-sample-sql-02"] is Verdict.SUPPORTED
    assert verdicts["hcwsamplestprod01"] is Verdict.SUPPORTED
    assert verdicts["hcw-sample-pg-prod-01"] is Verdict.SUPPORTED
    assert verdicts["hcwsamplestdev01"] is Verdict.NOT_APPLICABLE  # env=dev
    assert verdicts["hcw-sample-kv-prod-01"] is Verdict.NOT_APPLICABLE  # not in the selector
    assert result.summary.supported == 3 and result.summary.contradicted == 2 and result.summary.unknown == 0
    assert result.summary.score == 60.0 and result.summary.coverage == 1.0
    assert len(result.contradictions) == 2
    [proposal] = result.proposals
    assert proposal.kind is ProposalKind.CONTRADICTION
    assert set(proposal.impactedResourceIds) == {c.resourceId for c in result.contradictions}
    assert proposal.claimIds == [decision.claims[0].claimId]


def test_no_evidence_is_unknown_not_contradicted(decision, now):
    result = evaluate_decision(decision, [], now=now)
    [finding] = result.findings
    assert finding.verdict is Verdict.UNKNOWN and finding.resourceId is None
    assert result.summary.coverage == 0.0 and result.summary.score is None
    assert result.contradictions == [] and result.proposals == []


def test_expired_or_too_old_evidence_is_unknown(decision, sample_export, now):
    old = imported(sample_export, now - timedelta(hours=48))
    assert evaluate_decision(decision, [old], now=now).findings[0].verdict is Verdict.UNKNOWN
    expired = imported(sample_export, now, ttl_override=timedelta(minutes=1))
    assert evaluate_decision(decision, [expired], now=now + timedelta(minutes=2)).findings[0].verdict is Verdict.UNKNOWN


def test_wrong_class_is_not_usable(decision, now):
    declared = ingest(
        kind=EvidenceKind.CUSTOM,
        evidence_class=EvidenceClass.DECLARED,
        payload={"resources": []},
        subject=Subject(scope=ScopeKind.DECISION),
        provenance=SourceProvenance(sourceType=SourceType.HUMAN),
        authenticated=True,
        now=now,
    )
    assert evaluate_decision(decision, [declared], now=now).findings[0].verdict is Verdict.UNKNOWN


def test_decision_scope_filters_resources(sample_export, now):
    decision = make_decision(
        scope=DecisionScope(resourceGroupNames=["rg-hcw-sample-dev"], tagSelectors={"owner": "data-platform"})
    )
    result = evaluate_decision(decision, [imported(sample_export, now)], now=now)
    assert by_name(result) == {"hcwsamplestdev01": Verdict.NOT_APPLICABLE}  # env=dev fails the claim selector
    other = make_decision(scope=DecisionScope(subscriptionIds=["00000000-0000-0000-0000-000000000002"]))
    assert evaluate_decision(other, [imported(sample_export, now)], now=now).findings[0].verdict is Verdict.UNKNOWN


def test_later_record_of_the_same_resource_wins(decision, sample_export, now):
    fixed = {"data": [dict(sample_export["data"][0], properties={"zoneRedundant": True})]}
    result = evaluate_decision(decision, [imported(sample_export, now), imported(fixed, now)], now=now)
    assert by_name(result)["hcw-sample-sql-01"] is Verdict.SUPPORTED


def test_summary_weights_by_severity(decision):
    from cloud_crawler_core.ids import new_id
    from cloud_crawler_core.models import DriftFinding

    def finding(verdict):
        return DriftFinding(
            findingId=new_id("finding"),
            claimId=decision.claims[0].claimId,
            decisionId=decision.decisionId,
            verdict=verdict,
            detectorId="zone-redundancy",
            detectorVersion="1.0.0",
            evaluatedAt=decision.createdAt,
        )

    summary = summarise(
        decision,
        [
            finding(Verdict.SUPPORTED),
            finding(Verdict.CONTRADICTED),
            finding(Verdict.UNKNOWN),
            finding(Verdict.NOT_APPLICABLE),
        ],
    )
    assert summary.score == 50.0 and summary.coverage == 0.667 and summary.notApplicable == 1
    assert summarise(decision, []).score is None and summarise(decision, []).coverage is None
