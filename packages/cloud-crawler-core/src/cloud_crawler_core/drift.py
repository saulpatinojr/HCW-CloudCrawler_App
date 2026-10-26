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
from cloud_crawler_core.detectors.base import EvidenceDetector, tag_of
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
    EvidenceKind,
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


def _scope_state(decision: DecisionRecord, resource: NormalizedResource) -> bool | None:
    """Is the resource in the decision's scope? None when the scope names tags and the row's tags are not carried by its
    evidence: the row is neither in nor out, and each claim answers `unknown` for it."""
    scope = decision.scope
    if scope.subscriptionIds and (resource.subscriptionId or "") not in {s.lower() for s in scope.subscriptionIds}:
        return False
    if scope.resourceGroupNames and (resource.resourceGroup or "").lower() not in {
        g.lower() for g in scope.resourceGroupNames
    }:
        return False
    if scope.tagSelectors:
        if "tags" in resource.notCarried:
            return None
        return all(tag_of(resource, key) == value for key, value in scope.tagSelectors.items())
    return True


def _rank(evidence: Evidence) -> int:
    """A plan describes what Terraform would build, not what exists: its rows never replace the rows of any other kind
    for the same resource, whichever record is later. Among records of one rank the later record wins."""
    return 0 if evidence.kind is EvidenceKind.TF_PLAN else 1


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
        if isinstance(detector, EvidenceDetector):
            findings.extend(detector.evaluate(claim, usable, scope=decision.scope, now=now))
            continue
        resources: dict[str, tuple[int, NormalizedResource, str]] = {}  # id -> (rank, row, the record it came from)
        undecided: dict[str, tuple[int, NormalizedResource, str]] = {}
        out_of_scope: set[str] = set()  # ids an observed record put out of scope
        for record in usable:
            rank = _rank(record)
            for row in resources_of(record):
                state = _scope_state(decision, row)
                if state is False:
                    if rank > 0:
                        out_of_scope.add(row.id)
                    continue
                target = resources if state else undecided
                current = target.get(row.id)
                if current is None or rank >= current[0]:  # a later record of the same resource wins, of equal rank
                    target[row.id] = (rank, row, record.evidenceId)
        # An observed row that puts a resource out of the scope, or that cannot be placed in it, outranks a plan row
        # of the same resource: the plan cannot bring it back in, and cannot answer for it.
        observed_elsewhere = out_of_scope | {rid for rid, entry in undecided.items() if entry[0] > 0}
        for rid in observed_elsewhere:
            if rid in resources and resources[rid][0] == 0:
                del resources[rid]
        unsure = {rid: entry for rid, entry in undecided.items() if rid not in resources and rid not in out_of_scope}
        if not resources and not unsure:
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
        if resources:
            evaluated = detector.evaluate(claim, [row for _, row, _ in resources.values()], evidence_ids=[], now=now)
            for finding in evaluated:
                if finding.resourceId in resources:
                    finding.evidenceIds = [resources[finding.resourceId][2]]
            findings.extend(evaluated)
        for _, row, evidence_id in unsure.values():
            finding = detector.undecided(
                claim,
                row,
                "the evidence behind this resource does not carry its tags, so the decision's scope cannot be applied",
                evidence_ids=[evidence_id],
                now=now,
            )
            if finding is not None:
                findings.append(finding)
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
        if claim.detectorId == "retirement-exposure":
            proposals.append(_retirement_proposal(decision, claim, items, evidence_ids, now))
            continue
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


def _retirement_proposal(
    decision: DecisionRecord,
    claim: Claim,
    items: list[Contradiction],
    evidence_ids: list[str],
    now: datetime,
) -> ReviewProposal:
    """What a retirement asks the architects to decide (website proposal, section 14): the impacted resources, the
    date, the Advisor description and remediation, and migration considerations assembled by rule."""
    dates = sorted({str(c.observed.get("retirementDate")) for c in items if c.observed.get("retirementDate")})
    features = sorted(
        {str(c.observed.get("retirementFeatureName")) for c in items if c.observed.get("retirementFeatureName")}
    )
    due = datetime.fromisoformat(dates[0]).replace(tzinfo=UTC) if dates else None
    actions = [
        RecommendedAction(action=str(c.observed["solution"]), source="advisor", destructive=False)
        for c in items
        if c.observed.get("solution")
    ]
    seen: set[str] = set()
    actions = [a for a in actions if not (a.action in seen or seen.add(a.action))]
    return ReviewProposal(
        proposalId=new_id("proposal"),
        kind=ProposalKind.RETIREMENT,
        decisionId=decision.decisionId,
        claimIds=[claim.claimId],
        evidenceIds=evidence_ids,
        impactedResourceIds=[c.resourceId for c in items if c.resourceId],
        title="Service retirement: "
        + (", ".join(features) if features else "a service in scope")
        + (f" on {dates[0]}" if dates else ""),
        rationale=(
            f"{len(items)} resource(s) in scope of decision {decision.decisionId} depend on a service that Advisor "
            f"reports as retiring within {claim.parameters.get('withinDays', 180)} days (claim {claim.claimId})."
        ),
        migrationConsiderations=[
            "Confirm the retirement date and the replacement offering in the Advisor notice and Service Health",
            "Check whether the replacement keeps the decision's claims (zone redundancy, private access, region)",
            "Plan data migration and cut-over before the retirement date; record the accepted risk if it slips",
        ],
        recommendedActions=actions
        or [
            RecommendedAction(action="Migrate to the replacement offering before the retirement date", source="catalog")
        ],
        dueBy=due,
        createdAt=now,
    )


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
