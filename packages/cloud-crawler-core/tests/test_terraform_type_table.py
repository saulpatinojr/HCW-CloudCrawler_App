"""The provider-type table is a contract, like the detector ids: types are added, never renamed or dropped (ADR 0002 and
0005), and every type the wave-one detectors read has a Terraform mapping (ticket #54).

The snapshot `snapshots/terraform-type-table.json` lists each Terraform type and the Azure type it becomes. Adding a
type means adding a line to it in the same change; a changed or missing line is a reviewed decision, never a silent one.
Regenerate with CC_UPDATE_SNAPSHOT=1, locally, and read the diff.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from cloud_crawler_core.detectors import DETECTORS, Detector
from cloud_crawler_core.normalize.terraform_types import NODE_POOL_TYPE, TYPE_TABLE
from terraform_fixtures import arm_id, rows_of_state, state_record

SNAPSHOT = Path(__file__).with_name("snapshots") / "terraform-type-table.json"

# Azure types a wave-one detector reads that have no Terraform mapping, with the reason. Empty: every one is mapped.
UNMAPPED_BY_DECISION: dict[str, str] = {}


def current() -> dict[str, str]:
    return {name: mapping.arm_type for name, mapping in sorted(TYPE_TABLE.items())}


def test_the_table_matches_the_committed_snapshot():
    if os.environ.get("CC_UPDATE_SNAPSHOT") == "1":
        SNAPSHOT.write_text(json.dumps(current(), indent=2) + "\n", encoding="utf-8", newline="\n")
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert current() == committed, "the type table changed: review the difference, then CC_UPDATE_SNAPSHOT=1"


def test_a_snapshot_line_is_never_renamed_or_dropped():
    # Stricter than equality when the snapshot is regenerated carelessly: whatever a past snapshot named must remain.
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    for terraform_type, arm_type in committed.items():
        assert TYPE_TABLE[terraform_type].arm_type == arm_type


def test_every_azure_type_a_detector_reads_has_a_terraform_mapping():
    read = {
        arm_type
        for detector in DETECTORS.values()
        if isinstance(detector, Detector)
        for arm_type in detector.resource_types
        if arm_type != "*"
    }
    mapped = {mapping.arm_type for mapping in TYPE_TABLE.values()}
    assert sorted(read - mapped) == sorted(UNMAPPED_BY_DECISION), (
        "a detector reads an Azure type with no Terraform type (or the decision list is stale)"
    )
    assert not set(UNMAPPED_BY_DECISION) & mapped


def test_the_table_only_names_azurerm_types_and_lower_case_azure_types():
    for terraform_type, mapping in TYPE_TABLE.items():
        assert terraform_type.startswith("azurerm_") and terraform_type == terraform_type.lower()
        assert mapping.arm_type == mapping.arm_type.lower() and mapping.arm_type.startswith("microsoft.")
        assert mapping.arm_type.count("/") >= 1


def test_the_node_pool_is_folded_into_its_cluster_and_is_not_a_table_type():
    assert NODE_POOL_TYPE not in TYPE_TABLE
    assert "microsoft.containerservice/managedclusters" in {m.arm_type for m in TYPE_TABLE.values()}


@pytest.mark.parametrize("terraform_type", sorted(TYPE_TABLE))
def test_a_bare_instance_of_every_type_gives_a_row_that_says_only_what_it_was_given(terraform_type):
    arm_type = TYPE_TABLE[terraform_type].arm_type
    attributes = {"id": arm_id("Microsoft.Test", "things", "one"), "name": "one"}
    [row] = rows_of_state(state_record(terraform_type, "one", attributes))
    assert row.type == arm_type and row.name == "one"
    assert row.properties == {} and row.sku == {} and row.zones == [] and row.identity == {} and row.tags == {}
    # nothing was said about tags or identity, so the row says it cannot answer for them
    assert {"tags", "identity"} <= set(row.notCarried)
