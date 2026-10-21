"""The drift engine: a decision's claims against the evidence in hand.

For each claim: the detector runs over every normalised resource carried by evidence that is of a required class,
not expired, and not below the claim's evidence requirement. Findings feed contradictions (one per claim and
resource) and one review proposal per contradicted claim. Scoring follows the program rule: the score is the
severity-weighted share of supported findings among observed ones; unknown lowers coverage, never score.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from cloud_crawler_core.detectors import get_detector
from cloud_crawler_core.detectors.base import tag_of
from cloud_crawler_core.ids import new_id
from cloud_crawler_core.ingest import resources_of
from cloud_crawler_core.models import (
    SEVERITY_WEIGHTS,
    Claim,
    Contradiction,
    DecisionRecord,
    DriftFinding,
    DriftResult,
    DriftSummary,
    Evidence,
    EvidenceClass,
    EvidenceRequirement,
    NormalizedResource,
    ProposalKind,
    RecommendedAction,
    ReviewProposal,
    Verdict,
)

DEFAULT_REQUIREMENT = EvidenceRequirement(claimId="", requiredClasses=[EvidenceClass.OBSERVED, EvidenceClass.IMPORTED])


def _requirement_for(decision: DecisionRecord, claim: Claim) -> EvidenceRequirement:
    for requirement in decision.evidenceRequirements:
        if requirement.claimId == claim.claimId:
            return requirement
    return DEFAULT_REQUIREMENT


def _usable(evidence: Evidence, requirement: EvidenceRequirement, now: datetime) -> bool:
    if evidence.evidenceClass not in requirement.requiredClasses:
        return False
    if evidence.expiresAt is not None and evidence.expiresAt <= now:
        return False
    age_hours = (now - evidence.retrievedAt).total_seconds() / 3600
    return age_hours <= requirement.maxAgeHours


def _in_scope(decision: DecisionRecord, resource: NormalizedResource) -> bool:
    scope = decision.scope
    if scope.subscriptionIds and (resource.subscriptionId or "") not in {s.lower() for s in scope.subscriptionIds}:
        return False
    if scope.resourceGroupNames and (resource.resourceGroup or "").lower() not in {
        g.lower() for g in scope.resourceGroupNames
    }:
        return False
    return all(tag_of(resource, key) == value for key, value in scope.tagSelectors.items())


def evaluate_decision(
    decision: DecisionRecord,
    evidence: list[Evidence],
    *,
    now: datetime | None = None,
) -> DriftResult:
    now = now or datetime.now(UTC)
    findings: list[DriftFinding] = []
    for claim in decision.claims:
        detector = get_detector(claim.detectorId)
        requirement = _requirement_for(decision, claim)
        usable = [e for e in evidence if _usable(e, requirement, now)]
        resources: dict[str, NormalizedResource] = {}
        evidence_ids: list[str] = []
        for record in usable:
            rows = [r for r in resources_of(record) if _in_scope(decision, r)]
            if rows:
                evidence_ids.append(record.evidenceId)
            for row in rows:
                resources[row.id] = row  # a later record of the same resource wins
        if not resources:
            findings.append(
                DriftFinding(
                    findingId=new_id("finding"),
                    claimId=claim.claimId,
                    decisionId=decision.decisionId,
                    verdict=Verdict.UNKNOWN,
                    expected={claim.expectation.property: claim.expectation.value},
                    unknownReason=(
                        "no usable evidence in scope (none, expired, or of a class the claim does not accept)"
                    ),
                    detectorId=detector.detector_id,
                    detectorVersion=detector.version,
                    evaluatedAt=now,
                )
            )
            continue
        findings.extend(detector.evaluate(claim, resources.values(), evidence_ids=evidence_ids, now=now))
    contradictions = _contradictions(findings, now)
    proposals = _proposals(decision, findings, contradictions, now)
    return DriftResult(
        decisionId=decision.decisionId,
        evaluatedAt=now,
        findings=findings,
        contradictions=contradictions,
        proposals=proposals,
        summary=summarise(decision, findings),
    )


def _contradictions(findings: list[DriftFinding], now: datetime) -> list[Contradiction]:
    return [
        Contradiction(
            contradictionId=new_id("contradiction"),
            claimId=f.claimId,
            decisionId=f.decisionId,
            resourceId=f.resourceId,
            evidenceIds=list(f.evidenceIds),
            observed=dict(f.observed),
            expected=dict(f.expected),
            firstSeenAt=now,
            lastSeenAt=now,
        )
        for f in findings
        if f.verdict is Verdict.CONTRADICTED
    ]


def _proposals(
    decision: DecisionRecord, findings: list[DriftFinding], contradictions: list[Contradiction], now: datetime
) -> list[ReviewProposal]:
    by_claim: dict[str, list[Contradiction]] = defaultdict(list)
    for contradiction in contradictions:
        by_claim[contradiction.claimId].append(contradiction)
    claims = {c.claimId: c for c in decision.claims}
    proposals: list[ReviewProposal] = []
    for claim_id, items in by_claim.items():
        claim = claims[claim_id]
        resource_ids = [c.resourceId for c in items if c.resourceId]
        evidence_ids = sorted({eid for c in items for eid in c.evidenceIds})
        proposals.append(
            ReviewProposal(
                proposalId=new_id("proposal"),
                kind=ProposalKind.CONTRADICTION,
                decisionId=decision.decisionId,
                claimIds=[claim_id],
                evidenceIds=evidence_ids,
                impactedResourceIds=resource_ids,
                title=f"Claim contradicted: {claim.statement}",
                rationale=(
                    f"{len(items)} resource(s) in scope of decision {decision.decisionId} contradict claim "
                    f"{claim_id} ({claim.detectorId}, severity {claim.severity.value})."
                ),
                recommendedActions=[
                    RecommendedAction(action="Bring the resource(s) in line with the decision", source="catalog"),
                    RecommendedAction(
                        action="Or revise the decision and record the accepted risk", source="catalog", effort="low"
                    ),
                ],
                createdAt=now,
            )
        )
    return proposals


def summarise(decision: DecisionRecord, findings: list[DriftFinding]) -> DriftSummary:
    weights = {c.claimId: SEVERITY_WEIGHTS[c.severity] for c in decision.claims}
    summary = DriftSummary()
    supported_weight = 0
    observed_weight = 0
    for finding in findings:
        weight = weights.get(finding.claimId, 1)
        if finding.verdict is Verdict.SUPPORTED:
            summary.supported += 1
            supported_weight += weight
            observed_weight += weight
        elif finding.verdict is Verdict.CONTRADICTED:
            summary.contradicted += 1
            observed_weight += weight
        elif finding.verdict is Verdict.UNKNOWN:
            summary.unknown += 1
        else:
            summary.notApplicable += 1
    observed = summary.supported + summary.contradicted
    summary.score = round(100.0 * supported_weight / observed_weight, 1) if observed_weight else None
    summary.coverage = round(observed / (observed + summary.unknown), 3) if (observed + summary.unknown) else None
    return summary
