"""The evidence-reading detectors over the recorded Azure MCP results, through the drift engine."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from cloud_crawler_core.detectors import DETECTORS, EvidenceDetector
from cloud_crawler_core.drift import evaluate_decision
from cloud_crawler_core.ingest import ingest
from cloud_crawler_core.models import (
    DecisionScope,
    Evidence,
    EvidenceClass,
    EvidenceKind,
    Expectation,
    Operator,
    ProposalKind,
    ScopeKind,
    Selector,
    SourceProvenance,
    SourceType,
    Subject,
    Verdict,
)
from core_fixtures import NOW, SAMPLES, make_decision

RECORDINGS = SAMPLES / "azure-mcp"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
INITIATIVE = "/providers/Microsoft.Authorization/policySetDefinitions/00000000-0000-0000-0000-000000000031"


def observed(name: str, tool: str) -> Evidence:
    payload = json.loads((RECORDINGS / f"{name}.json").read_text(encoding="utf-8"))["structuredContent"]
    return ingest(
        kind=EvidenceKind.AZURE_MCP_RESULT,
        evidence_class=EvidenceClass.OBSERVED,
        payload=payload,
        subject=Subject(scope=ScopeKind.SUBSCRIPTION, subscriptionId=SUBSCRIPTION),
        provenance=SourceProvenance(sourceType=SourceType.AZURE_MCP, tool=tool, serverVersion="3.0.0"),
        authenticated=True,
        now=NOW,
    )


@pytest.fixture
def advisor() -> list[Evidence]:
    return [
        observed("advisor_recommendation_list", "advisor_recommendation_list"),
        observed("advisor_recommendation_list.retirement", "advisor_recommendation_list"),
    ]


@pytest.fixture
def policy() -> list[Evidence]:
    return [observed("policy_assignment_list", "policy_assignment_list")]


def decision(detector_id: str, expectation: Expectation, parameters: dict | None = None, **kwargs):
    record = make_decision(detector_id=detector_id, expectation=expectation, selector=Selector(), **kwargs)
    claim = record.claims[0].model_copy(update={"parameters": parameters or {}})
    return record.model_copy(update={"claims": [claim]})


def test_registry_holds_the_three_evidence_detectors():
    for detector_id in ("advisor-findings", "retirement-exposure", "policy-assignment-present"):
        assert isinstance(DETECTORS[detector_id], EvidenceDetector)
        assert DETECTORS[detector_id].tools


def test_advisor_findings_contradicts_new_and_notes_dismissed(advisor):
    result = evaluate_decision(
        decision("advisor-findings", Expectation(property="openFindings", operator=Operator.EQ, value=0)),
        advisor,
        now=NOW,
    )
    by_resource = {f.resourceId.rsplit("/", 1)[-1]: f for f in result.findings}
    assert by_resource["hcw-sample-sql-01"].verdict is Verdict.CONTRADICTED
    assert by_resource["hcw-sample-sql-01"].observed["openFindings"] == 1
    dismissed = by_resource["hcw-sample-cosmos-prod-01"]
    assert dismissed.verdict is Verdict.SUPPORTED and dismissed.observed["acceptedRisk"] is True
    assert dismissed.observed["dismissReason"].startswith("Risk accepted")
    assert result.summary.contradicted == 1 and result.summary.supported == 1 and result.summary.unknown == 0
    assert all(f.evidenceIds == [advisor[0].evidenceId] for f in result.findings)  # each cites the record it read
    [proposal] = result.proposals
    assert proposal.kind is ProposalKind.CONTRADICTION


def test_advisor_findings_supported_when_nothing_matches(advisor):
    result = evaluate_decision(
        decision(
            "advisor-findings",
            Expectation(property="openFindings", operator=Operator.EQ, value=0),
            {"category": "Cost", "impact": "Low"},
        ),
        advisor,
        now=NOW,
    )
    [finding] = result.findings
    assert (
        finding.verdict is Verdict.SUPPORTED and finding.observed == {"openFindings": 0} and finding.resourceId is None
    )


def test_advisor_findings_respects_resource_types_and_scope(advisor):
    record = decision("advisor-findings", Expectation(property="openFindings", operator=Operator.EQ, value=0))
    claim = record.claims[0].model_copy(
        update={"selector": Selector(resourceTypes=["microsoft.documentdb/databaseaccounts"])}
    )
    result = evaluate_decision(record.model_copy(update={"claims": [claim]}), advisor, now=NOW)
    assert [f.verdict for f in result.findings] == [Verdict.SUPPORTED]  # only the dismissed Cosmos row matches
    out_of_scope = record.model_copy(
        update={"scope": DecisionScope(subscriptionIds=["00000000-0000-0000-0000-000000000009"])}
    )
    result = evaluate_decision(out_of_scope, advisor, now=NOW)
    [finding] = result.findings  # every row lies outside the scope: the records say nothing about it
    assert finding.verdict is Verdict.UNKNOWN and finding.evidenceIds == []


def test_evidence_detectors_answer_unknown_without_evidence(policy):
    result = evaluate_decision(
        decision("advisor-findings", Expectation(property="openFindings", operator=Operator.EQ, value=0)),
        policy,
        now=NOW,
    )
    [finding] = result.findings
    assert finding.verdict is Verdict.UNKNOWN and "advisor_recommendation_list" in (finding.unknownReason or "")
    assert result.summary.coverage == 0.0 and result.summary.score is None


def test_retirement_exposure_opens_a_retirement_proposal(advisor):
    result = evaluate_decision(
        decision(
            "retirement-exposure",
            Expectation(property="exposedResources", operator=Operator.EQ, value=0),
            {"withinDays": 180},
        ),
        advisor,
        now=NOW,
    )
    [finding] = result.findings
    assert finding.verdict is Verdict.CONTRADICTED and finding.resourceId.endswith("/hcw-sample-redis-01")
    assert finding.observed["retirementDate"] == "2027-03-31"
    [proposal] = result.proposals
    assert proposal.kind is ProposalKind.RETIREMENT and proposal.title.startswith("Service retirement: ")
    assert (
        "2027-03-31" in proposal.title
        and proposal.dueBy is not None
        and proposal.dueBy.date().isoformat() == "2027-03-31"
    )
    assert proposal.impactedResourceIds == [finding.resourceId]
    assert proposal.recommendedActions[0].source == "advisor" and proposal.recommendedActions[0].action.startswith(
        "Migrate"
    )
    assert len(proposal.migrationConsiderations) == 3


def test_retirement_exposure_window_and_past_dates(advisor):
    narrow = evaluate_decision(
        decision(
            "retirement-exposure",
            Expectation(property="exposedResources", operator=Operator.EQ, value=0),
            {"withinDays": 30},
        ),
        advisor,
        now=NOW,
    )
    [finding] = narrow.findings
    assert finding.verdict is Verdict.SUPPORTED and finding.observed == {"exposedResources": 0, "withinDays": 30}
    later = evaluate_decision(
        decision(
            "retirement-exposure",
            Expectation(property="exposedResources", operator=Operator.EQ, value=0),
            {"withinDays": 1},
        ),
        advisor,
        now=NOW + timedelta(days=400),  # the date is past: still exposed, never silently fine
    )
    assert later.findings[0].verdict is Verdict.UNKNOWN or later.summary.unknown == 1  # evidence expired by then


def test_retirement_notice_without_a_date_is_unknown():
    payload = json.loads((RECORDINGS / "advisor_recommendation_list.retirement.json").read_text())["structuredContent"]
    payload["recommendations"][0]["properties"]["extendedProperties"].pop("retirementDate")
    record = ingest(
        kind=EvidenceKind.AZURE_MCP_RESULT,
        evidence_class=EvidenceClass.OBSERVED,
        payload=payload,
        subject=Subject(scope=ScopeKind.SUBSCRIPTION, subscriptionId=SUBSCRIPTION),
        provenance=SourceProvenance(sourceType=SourceType.AZURE_MCP, tool="advisor_recommendation_list"),
        authenticated=True,
        now=NOW,
    )
    result = evaluate_decision(
        decision("retirement-exposure", Expectation(property="exposedResources", operator=Operator.EQ, value=0)),
        [record],
        now=NOW,
    )
    [finding] = result.findings
    assert finding.verdict is Verdict.UNKNOWN and "retirement date" in (finding.unknownReason or "")


def test_policy_assignment_present(policy):
    supported = evaluate_decision(
        decision(
            "policy-assignment-present",
            Expectation(property="assigned", operator=Operator.EQ, value=True),
            {"policyDefinitionId": INITIATIVE.upper(), "enforcementMode": "default"},
        ),
        policy,
        now=NOW,
    )
    [finding] = supported.findings
    assert finding.verdict is Verdict.SUPPORTED and finding.resourceId.endswith("/hcw-sample-baseline")
    assert finding.observed["scope"] == f"/subscriptions/{SUBSCRIPTION}"
    missing = evaluate_decision(
        decision(
            "policy-assignment-present",
            Expectation(property="assigned", operator=Operator.EQ, value=True),
            {"policyDefinitionId": INITIATIVE.replace("31", "32")},
        ),
        policy,
        now=NOW,
    )
    [finding] = missing.findings
    assert finding.verdict is Verdict.CONTRADICTED and finding.observed == {
        "assigned": False,
        "scope": f"/subscriptions/{SUBSCRIPTION}",
        "assignmentsAtScope": 1,
    }
    wrong_scope = evaluate_decision(
        decision(
            "policy-assignment-present",
            Expectation(property="assigned", operator=Operator.EQ, value=True),
            {
                "policyDefinitionId": INITIATIVE,
                "scope": f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-hcw-sample-prod",
            },
        ),
        policy,
        now=NOW,
    )
    assert wrong_scope.findings[0].verdict is Verdict.CONTRADICTED


@pytest.mark.parametrize(
    ("detector_id", "expectation", "parameters", "message"),
    [
        (
            "advisor-findings",
            Expectation(property="openFindings", operator=Operator.EQ, value=1),
            {},
            "takes expectation",
        ),
        (
            "retirement-exposure",
            Expectation(property="exposed", operator=Operator.EQ, value=0),
            {},
            "takes expectation",
        ),
        (
            "policy-assignment-present",
            Expectation(property="assigned", operator=Operator.NEQ, value=True),
            {},
            "takes expectation",
        ),
        (
            "policy-assignment-present",
            Expectation(property="assigned", operator=Operator.EQ, value=True),
            {},
            "policyDefinitionId",
        ),
    ],
)
def test_authoring_errors(detector_id, expectation, parameters, message, advisor, policy):
    with pytest.raises(ValueError, match=message):
        evaluate_decision(decision(detector_id, expectation, parameters), advisor + policy, now=NOW)
