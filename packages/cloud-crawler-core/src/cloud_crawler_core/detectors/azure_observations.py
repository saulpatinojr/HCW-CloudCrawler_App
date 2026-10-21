"""The detectors that read Azure MCP observations (website proposal, section 15 table): `advisor-findings`,
`retirement-exposure` and `policy-assignment-present`. Each reads the normalised rows of one tool's results
(`ingest.observations_of`), keeps the rows inside the decision's scope, and answers for the claim: one finding per
matching observation, or one finding saying nothing matched. The verdict rule of every detector holds: a row the
evidence does not carry is never a contradiction, and no usable evidence at all is `unknown` (the drift engine says
so before any detector runs).

Expectations are fixed by detector, as the table states them, and anything else is an authoring error:
- `advisor-findings`: `openFindings eq 0`. Parameters `category` (default HighAvailability) and `impact` (default
  High) select the rows. A `New` row in scope is contradicted; a `Dismissed` or `Postponed` row is supported and
  carries `acceptedRisk: true` with the Advisor dismiss reason (the proposal: those are not contradictions).
- `retirement-exposure`: `exposedResources eq 0`. Parameter `withinDays` (default 180). A `ServiceUpgradeAndRetirement`
  row whose retirement date is on or before now + withinDays (a date already past counts) is contradicted.
- `policy-assignment-present`: `assigned eq true`. Parameters `policyDefinitionId` (required, matched
  case-insensitively), `scope` (default the subscription of the decision's first scoped subscription, else any) and
  `enforcementMode` (optional).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from cloud_crawler_core.detectors.base import EvidenceDetector, scope_matches
from cloud_crawler_core.ingest import observations_of
from cloud_crawler_core.models import Claim, DecisionScope, DriftFinding, Evidence, Operator, Verdict

ADVISOR_LIST = "advisor_recommendation_list"
POLICY_LIST = "policy_assignment_list"
RETIREMENT_SUBCATEGORY = "serviceupgradeandretirement"
OPEN_STATUS = "new"
ACCEPTED_RISK_STATUSES = ("dismissed", "postponed")


def _require(claim: Claim, prop: str, value: Any) -> None:
    expectation = claim.expectation
    if expectation.property != prop or expectation.operator is not Operator.EQ or expectation.value != value:
        raise ValueError(
            f"claim {claim.claimId}: detector {claim.detectorId} takes expectation {prop} eq {value!r}, "
            f"got {expectation.property} {expectation.operator.value} {expectation.value!r}"
        )


def _rows(
    evidence: list[Evidence], tool: str, scope: DecisionScope
) -> tuple[list[tuple[dict[str, Any], str]], list[str]]:
    """The in-scope rows of every usable record of `tool`, each with the id of the record it came from, and the ids
    of every record that spoke for the scope (one that carried in-scope rows, or an empty result). A record whose
    rows all lie outside the scope says nothing about it."""
    rows: list[tuple[dict[str, Any], str]] = []
    evidence_ids: list[str] = []
    for record in evidence:
        parsed = observations_of(record)
        if parsed is None or parsed[0] != tool:
            continue
        kept = [r for r in parsed[1] if scope_matches(scope, r.get("subscriptionId"), r.get("resourceGroup"))]
        if kept or parsed[1] == []:
            evidence_ids.append(record.evidenceId)
        rows.extend((r, record.evidenceId) for r in kept)
    return rows, evidence_ids


def _types_match(claim: Claim, row: dict[str, Any]) -> bool:
    types = {t.lower() for t in claim.selector.resourceTypes}
    return not types or (row.get("impactedField") or "") in types


class AdvisorFindings(EvidenceDetector):
    detector_id = "advisor-findings"
    question = "Are there open Advisor recommendations of the claimed category and impact in scope?"
    tools = (ADVISOR_LIST,)

    def evaluate(
        self, claim: Claim, evidence: list[Evidence], *, scope: DecisionScope, now: datetime
    ) -> list[DriftFinding]:
        _require(claim, "openFindings", 0)
        category = str(claim.parameters.get("category", "HighAvailability")).lower()
        impact = str(claim.parameters.get("impact", "High")).lower()
        rows, evidence_ids = _rows(evidence, ADVISOR_LIST, scope)
        if not evidence_ids:
            return [
                self.finding(
                    claim,
                    Verdict.UNKNOWN,
                    resource_id=None,
                    observed={},
                    evidence_ids=[],
                    now=now,
                    unknown_reason="no usable advisor_recommendation_list result in scope",
                )
            ]
        findings: list[DriftFinding] = []
        for row, evidence_id in rows:
            if (row.get("category") or "").lower() != category or (row.get("impact") or "").lower() != impact:
                continue
            if not _types_match(claim, row):
                continue
            status = (row.get("status") or "").lower()
            observed = {
                "openFindings": 1 if status == OPEN_STATUS else 0,
                "status": row.get("status"),
                "recommendationTypeId": row.get("recommendationTypeId"),
                "problem": row.get("problem"),
            }
            if status == OPEN_STATUS:
                verdict = Verdict.CONTRADICTED
            elif status in ACCEPTED_RISK_STATUSES:
                verdict = Verdict.SUPPORTED
                observed["acceptedRisk"] = True
                observed["dismissReason"] = row.get("dismissReason")
            else:
                continue  # Completed: nothing open, nothing to note
            findings.append(
                self.finding(
                    claim,
                    verdict,
                    resource_id=row.get("resourceId"),
                    observed=observed,
                    evidence_ids=[evidence_id],
                    now=now,
                )
            )
        if not findings:
            findings.append(
                self.finding(
                    claim,
                    Verdict.SUPPORTED,
                    resource_id=None,
                    observed={"openFindings": 0},
                    evidence_ids=evidence_ids,
                    now=now,
                )
            )
        return findings


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00")).date() if "T" in value else date.fromisoformat(value)
        )
    except ValueError:
        return None


class RetirementExposure(EvidenceDetector):
    detector_id = "retirement-exposure"
    question = "Does a resource in scope depend on a service retiring within the claimed window?"
    tools = (ADVISOR_LIST,)

    def evaluate(
        self, claim: Claim, evidence: list[Evidence], *, scope: DecisionScope, now: datetime
    ) -> list[DriftFinding]:
        _require(claim, "exposedResources", 0)
        within = int(claim.parameters.get("withinDays", 180))
        horizon = (now.astimezone(UTC) + timedelta(days=within)).date()
        rows, evidence_ids = _rows(evidence, ADVISOR_LIST, scope)
        if not evidence_ids:
            return [
                self.finding(
                    claim,
                    Verdict.UNKNOWN,
                    resource_id=None,
                    observed={},
                    evidence_ids=[],
                    now=now,
                    unknown_reason="no usable advisor_recommendation_list result in scope",
                )
            ]
        findings: list[DriftFinding] = []
        for row, evidence_id in rows:
            if (row.get("subCategory") or "").lower() != RETIREMENT_SUBCATEGORY or not _types_match(claim, row):
                continue
            retirement = _parse_date(row.get("retirementDate"))
            observed = {
                "exposedResources": 1,
                "retirementDate": row.get("retirementDate"),
                "retirementFeatureName": row.get("retirementFeatureName"),
                "withinDays": within,
                "problem": row.get("problem"),
                "solution": row.get("solution"),
            }
            if retirement is None:
                findings.append(
                    self.finding(
                        claim,
                        Verdict.UNKNOWN,
                        resource_id=row.get("resourceId"),
                        observed=observed,
                        evidence_ids=[evidence_id],
                        now=now,
                        unknown_reason="the retirement notice carries no parseable retirement date",
                    )
                )
            elif retirement <= horizon:
                findings.append(
                    self.finding(
                        claim,
                        Verdict.CONTRADICTED,
                        resource_id=row.get("resourceId"),
                        observed=observed,
                        evidence_ids=[evidence_id],
                        now=now,
                    )
                )
        if not findings:
            findings.append(
                self.finding(
                    claim,
                    Verdict.SUPPORTED,
                    resource_id=None,
                    observed={"exposedResources": 0, "withinDays": within},
                    evidence_ids=evidence_ids,
                    now=now,
                )
            )
        return findings


class PolicyAssignmentPresent(EvidenceDetector):
    detector_id = "policy-assignment-present"
    question = "Is the declared policy definition or initiative assigned at the scope?"
    tools = (POLICY_LIST,)

    def evaluate(
        self, claim: Claim, evidence: list[Evidence], *, scope: DecisionScope, now: datetime
    ) -> list[DriftFinding]:
        _require(claim, "assigned", True)
        definition = str(claim.parameters.get("policyDefinitionId", "")).lower()
        if not definition:
            raise ValueError(f"claim {claim.claimId}: the parameter policyDefinitionId is required")
        wanted_scope = str(claim.parameters.get("scope", "")).lower() or (
            f"/subscriptions/{scope.subscriptionIds[0].lower()}" if scope.subscriptionIds else ""
        )
        mode = str(claim.parameters.get("enforcementMode", "")).lower()
        rows, evidence_ids = _rows(evidence, POLICY_LIST, scope)
        if not evidence_ids:
            return [
                self.finding(
                    claim,
                    Verdict.UNKNOWN,
                    resource_id=None,
                    observed={},
                    evidence_ids=[],
                    now=now,
                    unknown_reason="no usable policy_assignment_list result in scope",
                )
            ]
        matches = [
            (r, evidence_id)
            for r, evidence_id in rows
            if (r.get("policyDefinitionId") or "") == definition
            and (not wanted_scope or (r.get("scope") or "") == wanted_scope)
            and (not mode or (r.get("enforcementMode") or "").lower() == mode)
        ]
        if matches:
            return [
                self.finding(
                    claim,
                    Verdict.SUPPORTED,
                    resource_id=m.get("id"),
                    observed={"assigned": True, "scope": m.get("scope"), "enforcementMode": m.get("enforcementMode")},
                    evidence_ids=[evidence_id],
                    now=now,
                )
                for m, evidence_id in matches
            ]
        return [
            self.finding(
                claim,
                Verdict.CONTRADICTED,
                resource_id=None,
                observed={"assigned": False, "scope": wanted_scope or None, "assignmentsAtScope": len(rows)},
                evidence_ids=evidence_ids,
                now=now,
            )
        ]


ADVISOR_FINDINGS = AdvisorFindings()
RETIREMENT_EXPOSURE = RetirementExposure()
POLICY_ASSIGNMENT_PRESENT = PolicyAssignmentPresent()
