"""A Terraform plan describes what Terraform would build, not what exists (ticket #54, review finding F4).

A verdict from a plan is a verdict on what Terraform would build. So a plan row must never replace an observed row of
the same resource (a Resource Graph export, a Terraform state, an Azure MCP result), and a verdict that rests on a plan
alone must never close an open contradiction as fixed. A plan row still evaluates, and it can open a contradiction: a
plan that would build something the decision forbids is worth knowing before it is applied.

Before the fix, an export that showed the sample SQL database not zone redundant followed by a plan that would make it
zone redundant flipped the verdict to supported and closed the contradiction as `fixed`.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from cloud_crawler_core.drift import evaluate_decision
from cloud_crawler_core.ingest import ingest
from cloud_crawler_core.ledger import InMemoryLedger
from cloud_crawler_core.models import (
    ContradictionResolution,
    DecisionScope,
    DriftFinding,
    DriftResult,
    EvidenceClass,
    EvidenceKind,
    ScopeKind,
    Selector,
    SourceProvenance,
    SourceType,
    Subject,
    Verdict,
)
from core_fixtures import NOW, SAMPLES, make_decision
from terraform_fixtures import SUB, arm_id, change_entry, plan_of, state_of, state_record

SCOPE = Subject(scope=ScopeKind.SUBSCRIPTION, subscriptionId=SUB)
UPLOAD = SourceProvenance(sourceType=SourceType.UPLOAD, artifactName="document.json")
SERVER = arm_id("Microsoft.Sql", "servers", "hcw-sample-sqlsrv-01", group="rg-hcw-sample-prod")
DATABASE = SERVER + "/databases/hcw-sample-sql-01"


def database(zone_redundant: bool) -> dict[str, Any]:
    return {
        "id": DATABASE,
        "name": "hcw-sample-sql-01",
        "server_id": SERVER,
        "zone_redundant": zone_redundant,
        "tags": {"env": "prod"},
    }


def export_evidence(now):
    export = json.loads((SAMPLES / "sample-resource-graph.json").read_text(encoding="utf-8"))  # zoneRedundant false
    return take(EvidenceKind.ARG_EXPORT, export, now)


def plan_evidence(zone_redundant: bool, now):
    plan = plan_of(change_entry("azurerm_mssql_database", "sql_01", database(zone_redundant), actions=("update",)))
    return take(EvidenceKind.TF_PLAN, plan, now)


def state_evidence(zone_redundant: bool, now):
    state = state_of(state_record("azurerm_mssql_database", "sql_01", database(zone_redundant)))
    return take(EvidenceKind.TF_STATE, state, now)


def take(kind: EvidenceKind, payload: Any, now):
    return ingest(
        kind=kind,
        evidence_class=EvidenceClass.IMPORTED,
        payload=payload,
        subject=SCOPE,
        provenance=UPLOAD,
        authenticated=False,
        now=now,
    )


DECISION = make_decision(scope=DecisionScope(subscriptionIds=[SUB]))
LATER = NOW + timedelta(minutes=5)


def finding_for(result: DriftResult, name: str = "hcw-sample-sql-01") -> DriftFinding:
    return next(f for f in result.findings if f.resourceId and f.resourceId.endswith("/" + name))


def evaluate(ledger: InMemoryLedger, now) -> DriftResult:
    return ledger.record(evaluate_decision(DECISION, ledger.evidence_for(DECISION, now=now), now=now))


# --- the merge in the drift engine ------------------------------------------------------------------------------------


@pytest.mark.parametrize("plan_first", [False, True], ids=["plan after the export", "plan before the export"])
def test_a_plan_row_does_not_replace_an_observed_row_whatever_the_order(plan_first):
    export, plan = export_evidence(NOW), plan_evidence(True, NOW if plan_first else LATER)
    records = [plan, export] if plan_first else [export, plan]
    finding = finding_for(evaluate_decision(DECISION, records, now=LATER))
    assert finding.verdict is Verdict.CONTRADICTED  # the observed row says not zone redundant
    assert finding.evidenceIds == [export.evidenceId]  # and the finding cites the record it was judged on


def test_a_state_row_still_replaces_an_earlier_observed_row_as_before():
    # State describes what Terraform last applied. It is not a plan, so the later record still wins, as it always did.
    records = [export_evidence(NOW), state_evidence(True, LATER)]
    finding = finding_for(evaluate_decision(DECISION, records, now=LATER))
    assert finding.verdict is Verdict.SUPPORTED and finding.evidenceIds == [records[1].evidenceId]


def test_a_later_plan_replaces_an_earlier_plan_of_the_same_resource():
    records = [plan_evidence(False, NOW), plan_evidence(True, LATER)]
    finding = finding_for(evaluate_decision(DECISION, records, now=LATER))
    assert finding.verdict is Verdict.SUPPORTED and finding.evidenceIds == [records[1].evidenceId]


def test_an_observed_row_replaces_a_plan_row_even_when_the_plan_is_later_in_the_list():
    # the other direction of the same rule: observed beats plan, and equal kinds keep "the later record wins"
    records = [plan_evidence(True, NOW), state_evidence(False, LATER)]
    finding = finding_for(evaluate_decision(DECISION, records, now=LATER))
    assert finding.verdict is Verdict.CONTRADICTED and finding.evidenceIds == [records[1].evidenceId]


def test_a_plan_row_for_a_resource_nothing_else_observed_is_evaluated_and_cites_the_plan():
    plan = plan_evidence(False, NOW)
    finding = finding_for(evaluate_decision(DECISION, [plan], now=NOW))
    assert finding.verdict is Verdict.CONTRADICTED and finding.evidenceIds == [plan.evidenceId]


def test_each_finding_cites_the_record_its_row_came_from():
    export = export_evidence(NOW)  # thirteen resources
    extra = take(
        EvidenceKind.TF_PLAN,
        plan_of(
            change_entry("azurerm_mssql_database", "extra", {**database(True), "id": DATABASE + "2", "name": "x2"})
        ),
        LATER,
    )
    result = evaluate_decision(DECISION, [export, extra], now=LATER)
    assert finding_for(result, "hcw-sample-sql-01").evidenceIds == [export.evidenceId]
    assert finding_for(result, "hcw-sample-sql-012").evidenceIds == [extra.evidenceId]


# --- the ledger -------------------------------------------------------------------------------------------------------


def test_a_plan_does_not_close_an_open_contradiction_as_fixed():
    ledger = InMemoryLedger()
    ledger.add_evidence(export_evidence(NOW))
    first = evaluate(ledger, NOW)
    assert finding_for(first).verdict is Verdict.CONTRADICTED
    opened = [c for c in ledger.open_contradictions() if c.resourceId == DATABASE.lower()]
    assert len(opened) == 1
    ledger.add_evidence(plan_evidence(True, LATER))
    second = evaluate(ledger, LATER)
    assert finding_for(second).verdict is Verdict.CONTRADICTED  # the observed row still wins
    assert [c for c in ledger.open_contradictions() if c.resourceId == DATABASE.lower()] == opened or len(
        [c for c in ledger.open_contradictions() if c.resourceId == DATABASE.lower()]
    ) == 1
    assert ContradictionResolution.FIXED not in {c.resolution for c in ledger.contradictions.values()}


def test_a_verdict_that_rests_on_a_plan_alone_does_not_close_a_contradiction_either():
    # the observed evidence has expired; only the plan is left, and it says "supported"
    ledger = InMemoryLedger()
    ledger.add_evidence(export_evidence(NOW))
    evaluate(ledger, NOW)
    assert any(c.resourceId == DATABASE.lower() for c in ledger.open_contradictions())
    much_later = NOW + timedelta(days=8)  # an upload expires after seven days
    ledger.add_evidence(plan_evidence(True, much_later))
    result = evaluate(ledger, much_later)
    assert finding_for(result).verdict is Verdict.SUPPORTED
    assert any(c.resourceId == DATABASE.lower() and c.resolvedAt is None for c in ledger.contradictions.values())
    assert ContradictionResolution.FIXED not in {c.resolution for c in ledger.contradictions.values()}


def test_a_state_that_shows_the_fix_closes_the_contradiction_as_before():
    ledger = InMemoryLedger()
    ledger.add_evidence(export_evidence(NOW))
    evaluate(ledger, NOW)
    ledger.add_evidence(state_evidence(True, LATER))
    result = evaluate(ledger, LATER)
    assert finding_for(result).verdict is Verdict.SUPPORTED
    assert ContradictionResolution.FIXED in {c.resolution for c in ledger.contradictions.values()}


def test_a_plan_can_open_a_contradiction():
    ledger = InMemoryLedger()
    ledger.add_evidence(plan_evidence(False, NOW))
    result = evaluate(ledger, NOW)
    assert finding_for(result).verdict is Verdict.CONTRADICTED
    assert [c.resourceId for c in ledger.open_contradictions()] == [DATABASE.lower()]
    assert len(result.proposals) == 1


def test_the_ledger_rule_holds_for_a_finding_built_by_hand():
    # The ledger decides from the kinds of the records a finding cites, so it does not depend on the drift engine.
    ledger = InMemoryLedger()
    plan, export = plan_evidence(True, NOW), export_evidence(NOW)
    ledger.add_evidence(plan)
    ledger.add_evidence(export)
    evaluate(ledger, NOW + timedelta(days=8))  # nothing usable: nothing to close
    base = evaluate_decision(DECISION, [export], now=NOW)
    ledger.record(base)
    key = finding_for(base)
    supported_by_plan = key.model_copy(
        update={"findingId": "finding_x", "verdict": Verdict.SUPPORTED, "evidenceIds": [plan.evidenceId]}
    )
    ledger.record(DriftResult(decisionId=key.decisionId, evaluatedAt=LATER, findings=[supported_by_plan]))
    assert any(c.resolvedAt is None for c in ledger.contradictions.values())
    supported_by_both = supported_by_plan.model_copy(
        update={"findingId": "finding_y", "evidenceIds": [plan.evidenceId, export.evidenceId]}
    )
    ledger.record(DriftResult(decisionId=key.decisionId, evaluatedAt=LATER, findings=[supported_by_both]))
    assert ContradictionResolution.FIXED in {c.resolution for c in ledger.contradictions.values()}


def test_a_plan_cannot_bring_a_resource_into_scope_that_an_observed_row_put_out():
    # the dev storage account carries env=dev in the export; a plan that would tag it env=prod must not pull it in
    dev = arm_id("Microsoft.Storage", "storageAccounts", "hcwsamplestdev01", group="rg-hcw-sample-dev")
    after = {"id": dev, "name": "hcwsamplestdev01", "account_tier": "Standard", "account_replication_type": "LRS"}
    plan = take(
        EvidenceKind.TF_PLAN,
        plan_of(
            change_entry("azurerm_storage_account", "dev", {**after, "tags": {"env": "prod"}}, actions=("update",))
        ),
        LATER,
    )
    scope = DecisionScope(subscriptionIds=[SUB], tagSelectors={"env": "prod"})
    decision = make_decision(scope=scope, selector=Selector(resourceTypes=["microsoft.storage/storageaccounts"]))
    result = evaluate_decision(decision, [export_evidence(NOW), plan], now=LATER)
    assert not any(f.resourceId == dev.lower() for f in result.findings)
    assert any(f.resourceId and f.resourceId.endswith("hcwsamplestprod01") for f in result.findings)
