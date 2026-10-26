"""Values a plan cannot know until apply (ticket #54, review finding F1) and what a claim's selectors do with them (F5).

In a plan, an unknown map entry is left out of `after`, and `after_unknown` says so. Real Terraform 1.16.6 writes, for
`input = { a = "x", b = timestamp() }`, `after.input == {"a": "x"}` and `after_unknown.input == {"b": true}`
(`samples/terraform/terraform-data.plan-unknown.json`). A map of tags written that way looks complete, so the tag
claims `exists`, `neq` and `absent` would be answered from a map that is missing an entry: the row has to say it
cannot answer for its tags.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from cloud_crawler_core.detectors.governance import TAG_REQUIRED
from cloud_crawler_core.detectors.identity import MANAGED_IDENTITY
from cloud_crawler_core.detectors.zone_redundancy import ZONE_REDUNDANCY
from cloud_crawler_core.drift import evaluate_decision
from cloud_crawler_core.ingest import ingest
from cloud_crawler_core.models import (
    Claim,
    DecisionScope,
    EvidenceClass,
    EvidenceKind,
    Expectation,
    NormalizedResource,
    Operator,
    ScopeKind,
    Selector,
    SourceProvenance,
    SourceType,
    Subject,
    Verdict,
)
from cloud_crawler_core.normalize import parse_terraform_plan
from core_fixtures import NOW, SAMPLES, make_decision
from terraform_fixtures import SUB, change_entry, plan_of, row_of_plan

NOW_UTC = datetime(2026, 10, 26, tzinfo=UTC)
KEY_VAULT = {"name": "kv1", "resource_group_name": "rg", "location": "centralus", "identity": []}


def real_plan() -> dict:
    return json.loads((SAMPLES / "terraform" / "terraform-data.plan-unknown.json").read_text(encoding="utf-8"))


def test_real_terraform_leaves_an_unknown_map_entry_out_and_says_so_in_after_unknown():
    changes = {c["address"]: c["change"] for c in real_plan()["resource_changes"]}
    partly = changes["terraform_data.partly_unknown"]
    assert partly["after"]["input"] == {"a": "x"}  # the entry b is not there ...
    assert partly["after_unknown"]["input"] == {"b": True}  # ... and only this says it is unknown
    listed = changes["terraform_data.list_unknown"]
    assert listed["after"]["input"] == ["1", None]  # a list keeps its place with null
    assert listed["after_unknown"]["input"] == [False, True]
    for address in ("terraform_data.partly_unknown", "terraform_data.list_unknown"):
        planned = {r["address"]: r for r in real_plan()["planned_values"]["root_module"]["resources"]}[address]
        assert "after_unknown" not in planned  # planned_values has no such marker at all


@pytest.mark.parametrize(
    "unknown",
    [
        {"tags": {"owner": True}},  # the real shape: an entry of the map
        {"tags": True},  # the whole map
        {"tags": {"a": False, "b": {"c": True}}},  # anywhere under it
    ],
)
def test_an_unknown_entry_at_or_under_tags_makes_the_tags_not_carried(unknown):
    row = row_of_plan("azurerm_key_vault", {**KEY_VAULT, "tags": {"env": "prod"}}, unknown=unknown, actions=("create",))
    assert row.tags == {"env": "prod"} and "tags" in row.notCarried


@pytest.mark.parametrize(
    "unknown", [{}, {"tags": {}}, {"tags": {"owner": False}}, {"id": True, "location": True}, False]
)
def test_nothing_unknown_under_tags_leaves_the_tags_carried(unknown):
    row = row_of_plan("azurerm_key_vault", {**KEY_VAULT, "tags": {"env": "prod"}}, unknown=unknown)
    assert "tags" not in row.notCarried


@pytest.mark.parametrize(
    "unknown",
    [
        {"identity": True},
        {"identity": [True]},
        {"identity": [{"type": True}]},
    ],
)
def test_an_unknown_identity_block_or_type_makes_the_identity_not_carried(unknown):
    after = {**KEY_VAULT, "tags": {}, "identity": [{"type": "SystemAssigned"}]}
    row = row_of_plan("azurerm_linux_web_app", after, unknown=unknown, actions=("create",))
    assert "identity" in row.notCarried


def test_the_computed_ids_of_an_identity_block_do_not_matter_to_the_detector():
    # Every new resource has an unknown principal_id and tenant_id; the detector reads the type, which is known.
    after = {**KEY_VAULT, "tags": {}, "identity": [{"type": "SystemAssigned"}]}
    unknown = {"id": True, "identity": [{"principal_id": True, "tenant_id": True}]}
    row = row_of_plan("azurerm_linux_web_app", after, unknown=unknown, actions=("create",))
    assert row.identity == {"type": "SystemAssigned"} and "identity" not in row.notCarried


@pytest.mark.parametrize(
    ("terraform_type", "attribute", "after", "unknown"),
    [
        ("azurerm_public_ip", "zones", {"zones": ["1", "2"]}, {"zones": [False, True]}),
        ("azurerm_public_ip", "zones", {"zones": ["1", "2"]}, {"zones": True}),
        ("azurerm_linux_virtual_machine_scale_set", "zones", {"zones": ["1"]}, {"zones": [True]}),
        ("azurerm_linux_virtual_machine", "zone", {"zone": "1"}, {"zone": True}),
    ],
)
def test_an_unknown_zone_makes_the_zones_not_carried(terraform_type, attribute, after, unknown):
    row = row_of_plan(terraform_type, {**KEY_VAULT, "tags": {}, "identity": [], **after}, unknown=unknown)
    assert "zones" in row.notCarried


def test_a_key_the_plan_does_not_say_is_unknown_about_leaves_the_row_as_it_was():
    row = row_of_plan("azurerm_public_ip", {**KEY_VAULT, "tags": {}, "zones": ["1"]}, unknown={"ip_address": True})
    assert row.zones == ["1"] and "zones" not in row.notCarried


def tag_claim(operator: Operator, value: Any = None, selector: Selector | None = None) -> Claim:
    return Claim(
        claimId="claim_1",
        decisionId="decision_1",
        statement="owner tag",
        detectorId="tag-required",
        parameters={"tag": "owner"},
        selector=selector or Selector(),
        expectation=Expectation(property="tag", operator=operator, value=value),
    )


@pytest.mark.parametrize(
    ("operator", "value", "without_the_fix"),
    [
        (Operator.EXISTS, None, Verdict.CONTRADICTED),
        (Operator.NEQ, "dev", Verdict.SUPPORTED),
        (Operator.ABSENT, None, Verdict.SUPPORTED),
        (Operator.EQ, "data-platform", Verdict.CONTRADICTED),
    ],
)
def test_a_tag_claim_on_tags_with_an_unknown_entry_is_unknown_not_a_false_answer(operator, value, without_the_fix):
    row = row_of_plan(
        "azurerm_key_vault",
        {**KEY_VAULT, "tags": {"env": "prod"}},
        unknown={"tags": {"owner": True}},
        actions=("create",),
    )
    [finding] = TAG_REQUIRED.evaluate(tag_claim(operator, value), [row], evidence_ids=["e"], now=NOW_UTC)
    assert finding.verdict is Verdict.UNKNOWN, f"{without_the_fix.value} is what the plan could not know"
    assert "tags" in finding.unknownReason


def test_identity_and_zone_claims_on_unknown_values_are_unknown_too():
    app = row_of_plan(
        "azurerm_linux_web_app",
        {**KEY_VAULT, "tags": {}, "identity": []},
        unknown={"identity": True},
        actions=("create",),
    )
    ip = row_of_plan("azurerm_public_ip", {**KEY_VAULT, "tags": {}, "zones": []}, unknown={"zones": True})
    identity_claim = Claim(
        claimId="c", decisionId="d", statement="has identity", detectorId="managed-identity", selector=Selector(),
        expectation=Expectation(property="managedIdentityAssigned", operator=Operator.EQ, value=True),
    )  # fmt: skip
    zone_claim = Claim(
        claimId="c", decisionId="d", statement="zone redundant", detectorId="zone-redundancy", selector=Selector(),
        expectation=Expectation(property="zoneRedundant", operator=Operator.EQ, value=True),
    )  # fmt: skip
    [identity] = MANAGED_IDENTITY.evaluate(identity_claim, [app], evidence_ids=["e"], now=NOW_UTC)
    [zones] = ZONE_REDUNDANCY.evaluate(zone_claim, [ip], evidence_ids=["e"], now=NOW_UTC)
    assert identity.verdict is Verdict.UNKNOWN and zones.verdict is Verdict.UNKNOWN


# --- the planned_values route has no after_unknown, so it cannot tell ------------------------------------------------


def planned_values_plan(values: dict, *, terraform_type: str = "azurerm_key_vault") -> dict:
    resource = {
        "address": f"{terraform_type}.main",
        "mode": "managed",
        "type": terraform_type,
        "name": "main",
        "provider_name": "registry.terraform.io/hashicorp/azurerm",
        "values": values,
    }
    return {"format_version": "1.2", "planned_values": {"root_module": {"resources": [resource]}}}


def test_the_planned_values_route_marks_tags_identity_and_zones_not_carried_because_it_cannot_tell():
    # planned_values drops what is unknown without saying so, so a map or a list can look complete when it is not.
    # (Real Terraform keeps a list element's place with null, which is read as unreadable anyway; a map entry just
    # disappears.) The same plan through resource_changes, which has after_unknown, keeps what it can answer.
    values = {**KEY_VAULT, "tags": {"env": "prod"}, "identity": []}
    [row] = parse_terraform_plan(planned_values_plan(values)).resources
    assert row.tags == {"env": "prod"} and row.identity == {}
    assert row.notCarried == ["identity", "tags"]
    [from_changes] = parse_terraform_plan(plan_of(change_entry("azurerm_key_vault", "main", values))).resources
    assert from_changes.notCarried == []


def test_the_planned_values_route_marks_zones_too():
    values = {**KEY_VAULT, "tags": {}, "zones": ["1"]}
    [row] = parse_terraform_plan(planned_values_plan(values, terraform_type="azurerm_public_ip")).resources
    assert "zones" in row.notCarried


def test_a_tag_claim_on_the_planned_values_route_is_unknown():
    [row] = parse_terraform_plan(planned_values_plan({**KEY_VAULT, "tags": {"env": "prod"}})).resources
    [finding] = TAG_REQUIRED.evaluate(tag_claim(Operator.EXISTS), [row], evidence_ids=["e"], now=NOW_UTC)
    assert finding.verdict is Verdict.UNKNOWN


# --- selectors (F5) ---------------------------------------------------------------------------------------------------


def row_without_known_tags() -> NormalizedResource:
    return NormalizedResource(
        id="terraform:azurerm_key_vault.new",
        type="microsoft.keyvault/vaults",
        name="new",
        subscriptionId=SUB,
        notCarried=["tags"],
    )


def test_a_claim_selector_on_tags_cannot_be_applied_to_a_row_whose_tags_are_not_carried():
    selector = Selector(resourceTypes=["microsoft.keyvault/vaults"], tagSelectors={"env": "prod"})
    [finding] = TAG_REQUIRED.evaluate(
        tag_claim(Operator.EXISTS, selector=selector), [row_without_known_tags()], evidence_ids=["e"], now=NOW_UTC
    )
    assert finding.verdict is Verdict.UNKNOWN and "selector" in finding.unknownReason


def test_the_other_parts_of_a_selector_still_decide_first():
    selector = Selector(resourceTypes=["microsoft.sql/servers"], tagSelectors={"env": "prod"})
    [finding] = TAG_REQUIRED.evaluate(
        tag_claim(Operator.EXISTS, selector=selector), [row_without_known_tags()], evidence_ids=["e"], now=NOW_UTC
    )
    assert finding.verdict is Verdict.NOT_APPLICABLE  # not a key vault whatever its tags are


def test_a_selector_without_tags_does_not_care_that_tags_are_not_carried():
    selector = Selector(resourceTypes=["microsoft.keyvault/vaults"])
    [finding] = TAG_REQUIRED.evaluate(
        tag_claim(Operator.EXISTS, selector=selector), [row_without_known_tags()], evidence_ids=["e"], now=NOW_UTC
    )
    assert finding.verdict is Verdict.UNKNOWN  # the tag claim itself cannot be answered, for its own reason
    assert "selector" not in finding.unknownReason


def storage_plan_with_unknown_tags() -> dict:
    after = {"name": "st", "account_tier": "Standard", "account_replication_type": "LRS", "identity": []}
    return plan_of(
        change_entry("azurerm_storage_account", "st", after, actions=("create",), unknown={"tags": True}),
    )


def test_a_decision_scope_tag_selector_leaves_such_a_row_unknown_not_silently_out_of_scope():
    scope = DecisionScope(subscriptionIds=[SUB], tagSelectors={"env": "prod"})
    decision = make_decision(scope=scope, selector=Selector(resourceTypes=["microsoft.storage/storageaccounts"]))
    evidence = ingest(
        kind=EvidenceKind.TF_PLAN,
        evidence_class=EvidenceClass.IMPORTED,
        payload=storage_plan_with_unknown_tags(),
        subject=Subject(scope=ScopeKind.SUBSCRIPTION, subscriptionId=SUB),
        provenance=SourceProvenance(sourceType=SourceType.UPLOAD, artifactName="plan.json"),
        authenticated=False,
        now=NOW,
    )
    [finding] = evaluate_decision(decision, [evidence], now=NOW).findings
    assert finding.verdict is Verdict.UNKNOWN and "scope" in finding.unknownReason
    assert finding.resourceId == "terraform:azurerm_storage_account.st"


def test_a_decision_scope_tag_selector_does_not_open_the_door_for_other_subscriptions():
    scope = DecisionScope(subscriptionIds=["another-subscription"], tagSelectors={"env": "prod"})
    decision = make_decision(scope=scope, selector=Selector(resourceTypes=["microsoft.storage/storageaccounts"]))
    evidence = ingest(
        kind=EvidenceKind.TF_PLAN,
        evidence_class=EvidenceClass.IMPORTED,
        payload=storage_plan_with_unknown_tags(),
        subject=Subject(scope=ScopeKind.SUBSCRIPTION, subscriptionId=SUB),
        provenance=SourceProvenance(sourceType=SourceType.UPLOAD, artifactName="plan.json"),
        authenticated=False,
        now=NOW,
    )
    [finding] = evaluate_decision(decision, [evidence], now=NOW).findings
    assert finding.verdict is Verdict.UNKNOWN and "no usable evidence in scope" in finding.unknownReason


def test_the_sample_estate_judgements_are_unchanged_by_all_of_this():
    # Only the rows that really cannot say anything change; every resource of the sample plan keeps its verdict.
    result = parse_terraform_plan(json.loads((SAMPLES / "terraform" / "sample-estate.plan.json").read_text("utf-8")))
    assert sorted(r.name for r in result.resources if r.notCarried) == [
        "hcw-sample-asp-prod-01",
        "hcw-sample-kv-prod-01",
        "hcw-sample-pip-new-01",
        "hcw-sample-pip-prod-01",
    ]
