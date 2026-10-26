"""Terraform state and plan -> NormalizedResource (ticket #54).

Each test says one thing about what the normaliser reads, and the thing it refuses to say: a property the document
cannot answer is absent (so the detector answers `unknown`), never defaulted; what Terraform marks sensitive is
withheld; a document is bounded before anything walks it.
"""

from __future__ import annotations

import ast
import json
import time
from pathlib import Path
from typing import Any

import pytest
from cloud_crawler_core.normalize import (
    IngestionError,
    check_json_bounds,
    parse_terraform_plan,
    parse_terraform_state,
)
from cloud_crawler_core.normalize import terraform as terraform_module
from core_fixtures import SAMPLES
from terraform_fixtures import (
    SUB,
    arm_id,
    attr_path,
    change_entry,
    plan_of,
    row_of_plan,
    row_of_state,
    rows_of_state,
    state_of,
    state_record,
)

SAMPLE_STATE = SAMPLES / "terraform" / "sample-estate.state.json"
SAMPLE_PLAN = SAMPLES / "terraform" / "sample-estate.plan.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _id(resource):
    return resource.id


# ---------------------------------------------------------------------------------------------------------------------
# The sample estate
# ---------------------------------------------------------------------------------------------------------------------


def test_the_sample_state_gives_one_row_per_resource_the_detectors_read():
    result = parse_terraform_state(load(SAMPLE_STATE))
    names = sorted(r.name for r in result.resources)
    assert len(names) == 13
    assert names == sorted(
        [
            "hcw-sample-sqlsrv-01",
            "hcw-sample-sql-01",
            "hcw-sample-sql-02",
            "hcwsamplestprod01",
            "hcwsamplestdev01",
            "hcw-sample-asp-prod-01",
            "hcw-sample-pg-prod-01",
            "hcw-sample-cosmos-prod-01",
            "hcw-sample-aks-prod-01",
            "hcw-sample-vm-prod-01",
            "hcw-sample-pip-prod-01",
            "hcw-sample-kv-prod-01",
            "hcw-sample-app-prod-01",
        ]
    )
    assert all(
        r.id.startswith(f"/subscriptions/{SUB}/resourcegroups/") and r.subscriptionId == SUB for r in result.resources
    )
    assert result.summary == {
        "source": "tf-state",
        "formatVersion": 4,
        "terraformVersion": "1.9.8",
        "instances": 18,
        "mapped": 13,
        "foldedIn": 1,
        "withoutAzureId": 0,
        "dataSources": 1,
        "unreadable": 0,
        "markersAbsent": 0,
        "destroyed": 0,
        "unmapped": {"azurerm_resource_group": 2, "azurerm_private_endpoint": 1, "azurerm_virtual_network": 1},
        "unmappedTypes": 3,
        "notCarried": {"identity": 3},
        "sensitiveMarked": 8,
    }


def test_the_sample_state_rows_are_what_resource_graph_names():
    rows = {r.name: r for r in parse_terraform_state(load(SAMPLE_STATE)).resources}
    storage = rows["hcwsamplestprod01"]
    assert storage.type == "microsoft.storage/storageaccounts"
    assert storage.sku == {"name": "Standard_ZRS", "tier": "Standard"}
    assert storage.properties == {"publicNetworkAccess": "Disabled"}
    assert storage.tags == {"env": "prod", "owner": "data-platform", "costCenter": "cc-1001"}
    assert storage.resourceGroup == "rg-hcw-sample-prod" and storage.location == "centralus"
    assert rows["hcw-sample-sql-01"].properties == {"zoneRedundant": False}
    assert rows["hcw-sample-sqlsrv-01"].identity == {"type": "SystemAssigned"}
    assert rows["hcw-sample-vm-prod-01"].identity == {"type": "UserAssigned"}
    assert rows["hcw-sample-pip-prod-01"].zones == ["1", "2", "3"]
    assert rows["hcw-sample-app-prod-01"].location == "eastus2"
    assert rows["hcw-sample-app-prod-01"].identity == {}  # an identity block that is empty: none is assigned
    cosmos = rows["hcw-sample-cosmos-prod-01"].properties["locations"]
    assert [loc["isZoneRedundant"] for loc in cosmos] == [True, False]
    pools = rows["hcw-sample-aks-prod-01"].properties["agentPoolProfiles"]
    assert [p["name"] for p in pools] == ["system", "user"]  # the default pool, then the node pool resource


def test_a_database_takes_its_servers_location():
    rows = {r.name: r for r in parse_terraform_state(load(SAMPLE_STATE)).resources}
    assert rows["hcw-sample-sql-01"].location == "centralus" == rows["hcw-sample-sqlsrv-01"].location


def test_the_sample_plan_gives_the_same_rows_as_its_planned_values():
    plan = load(SAMPLE_PLAN)
    from_changes = parse_terraform_plan(plan, default_subscription=SUB)
    without_changes = {k: v for k, v in plan.items() if k != "resource_changes"}
    from_planned = parse_terraform_plan(without_changes, default_subscription=SUB)

    # planned_values has no after_unknown, so it cannot tell a complete map or list from one that lost an entry: its
    # rows are the same except that they say they cannot answer for tags, identity and zones
    def bare(rows):
        return sorted((r.model_copy(update={"notCarried": []}) for r in rows), key=_id)

    assert bare(from_changes.resources) == bare(from_planned.resources)
    assert all({"tags", "identity"} <= set(r.notCarried) for r in from_planned.resources)
    changes_by_id = {r.id: r for r in from_changes.resources}
    assert all(set(changes_by_id[r.id].notCarried) <= set(r.notCarried) for r in from_planned.resources)
    assert len(from_changes.resources) == 15
    assert from_changes.summary["destroyed"] == 1 and "planActions" not in from_planned.summary
    assert from_changes.summary["planActions"] == {"create": 2, "delete": 1, "no-op": 17, "update": 1}


def test_the_sample_plan_matches_the_sample_state_for_the_resources_that_exist():
    state_rows = {r.id: r for r in parse_terraform_state(load(SAMPLE_STATE)).resources}
    plan_rows = {r.id: r for r in parse_terraform_plan(load(SAMPLE_PLAN), default_subscription=SUB).resources}
    assert state_rows.keys() <= plan_rows.keys()
    assert all(state_rows[i] == plan_rows[i] for i in state_rows)
    assert sorted(set(plan_rows) - set(state_rows)) == [
        "terraform:azurerm_public_ip.new",
        "terraform:azurerm_storage_account.logs",
    ]


def test_a_resource_the_plan_creates_is_keyed_by_its_address_and_takes_the_declared_subscription():
    plan = load(SAMPLE_PLAN)
    declared = parse_terraform_plan(plan, default_subscription="Declared-Subscription")
    logs = next(r for r in declared.resources if r.name == "hcwsamplestlogs01")
    assert logs.id == "terraform:azurerm_storage_account.logs"
    assert logs.subscriptionId == "declared-subscription" and logs.resourceGroup == "rg-hcw-sample-prod"
    # a row that has an Azure id keeps the subscription in the id, whatever the caller declared
    assert next(r for r in declared.resources if r.name == "hcwsamplestprod01").subscriptionId == SUB
    undeclared = parse_terraform_plan(plan)
    assert next(r for r in undeclared.resources if r.name == "hcwsamplestlogs01").subscriptionId is None
    assert undeclared.summary["withoutAzureId"] == 2


def test_tags_that_are_unknown_until_apply_are_not_carried_and_an_empty_identity_list_is_none():
    rows = {r.name: r for r in parse_terraform_plan(load(SAMPLE_PLAN)).resources}
    new_ip = rows["hcw-sample-pip-new-01"]
    assert new_ip.tags == {} and new_ip.notCarried == ["identity", "tags"]
    assert rows["hcwsamplestlogs01"].identity == {} and rows["hcwsamplestlogs01"].notCarried == []


def test_normalising_twice_gives_the_same_rows():
    state = load(SAMPLE_STATE)
    assert parse_terraform_state(state).resources == parse_terraform_state(json.loads(json.dumps(state))).resources


# ---------------------------------------------------------------------------------------------------------------------
# One mapping at a time. Every case is a statement about what the table reads from which attribute.
# ---------------------------------------------------------------------------------------------------------------------

BASE = {"name": "main", "tags": {}}


def attrs(terraform_type: str, **more: Any) -> dict[str, Any]:
    return {"id": arm_id("Microsoft.Test", terraform_type, "main"), **BASE, **more}


@pytest.mark.parametrize(
    ("terraform_type", "attributes", "expected"),
    [
        # storage account: the azurerm 3 and 4 flag, the azurerm 5 text, and what each means
        (
            "azurerm_storage_account",
            {"account_tier": "Premium", "account_replication_type": "GZRS", "public_network_access_enabled": True},
            {"sku": {"name": "Premium_GZRS", "tier": "Premium"}, "properties": {"publicNetworkAccess": "Enabled"}},
        ),
        (
            "azurerm_storage_account",
            {
                "account_tier": "Standard",
                "account_replication_type": "LRS",
                "public_network_access": "SecuredByPerimeter",
            },
            {
                "sku": {"name": "Standard_LRS", "tier": "Standard"},
                "properties": {"publicNetworkAccess": "SecuredByPerimeter"},
            },
        ),
        (
            "azurerm_storage_account",
            {"public_network_access": "disabled", "public_network_access_enabled": True},
            {
                "sku": {},
                "properties": {"publicNetworkAccess": "Disabled"},
            },  # the text wins; one tier or type is not a sku
        ),
        ("azurerm_storage_account", {"account_tier": "Standard"}, {"sku": {}, "properties": {}}),
        ("azurerm_storage_account", {"public_network_access": "Sometimes"}, {"properties": {}}),
        # sql
        (
            "azurerm_mssql_database",
            {"zone_redundant": True, "sku_name": "BC_Gen5_4"},
            {"sku": {"name": "BC_Gen5_4"}, "properties": {"zoneRedundant": True}},
        ),
        ("azurerm_mssql_database", {"zone_redundant": None}, {"properties": {}}),
        ("azurerm_mssql_database", {"zone_redundant": "true"}, {"properties": {}}),  # text is not a boolean
        (
            "azurerm_mssql_server",
            {"public_network_access_enabled": False},
            {"properties": {"publicNetworkAccess": "Disabled"}},
        ),
        # app service
        (
            "azurerm_service_plan",
            {"zone_balancing_enabled": True, "sku_name": "P1v3"},
            {"sku": {"name": "P1v3"}, "properties": {"zoneRedundant": True}},
        ),
        (
            "azurerm_linux_web_app",
            {"public_network_access_enabled": False},
            {"properties": {"publicNetworkAccess": "Disabled"}},
        ),
        (
            "azurerm_windows_function_app",
            {"public_network_access_enabled": True},
            {"properties": {"publicNetworkAccess": "Enabled"}},
        ),
        # postgres flexible server: the tier is the prefix of sku_name; no high availability block means disabled
        (
            "azurerm_postgresql_flexible_server",
            {
                "sku_name": "MO_Standard_E4s_v3",
                "high_availability": [{"mode": "SameZone"}],
                "public_network_access_enabled": False,
            },
            {
                "sku": {"name": "Standard_E4s_v3", "tier": "MemoryOptimized"},
                "properties": {
                    "highAvailability": {"mode": "SameZone"},
                    "network": {"publicNetworkAccess": "Disabled"},
                },
            },
        ),
        (
            "azurerm_postgresql_flexible_server",
            {"sku_name": "B_Standard_B1ms", "high_availability": []},
            {
                "sku": {"name": "Standard_B1ms", "tier": "Burstable"},
                "properties": {"highAvailability": {"mode": "Disabled"}},
            },
        ),
        (
            "azurerm_postgresql_flexible_server",
            {"sku_name": "XX_Standard_D2", "high_availability": [{"standby_availability_zone": "2"}]},
            {"sku": {}, "properties": {}},
        ),
        (
            "azurerm_postgresql_flexible_server",
            {"delegated_subnet_id": "/subscriptions/s/subnet", "public_network_access_enabled": False},
            {
                "properties": {
                    "network": {
                        "delegatedSubnetResourceId": "/subscriptions/s/subnet",
                        "publicNetworkAccess": "Disabled",
                    }
                }
            },
        ),
        # cosmos
        (
            "azurerm_cosmosdb_account",
            {
                "public_network_access_enabled": True,
                "geo_location": [
                    {"location": "eastus", "failover_priority": 0, "zone_redundant": True},
                    {"location": "westus", "failover_priority": 1},
                ],
            },
            {
                "properties": {
                    "publicNetworkAccess": "Enabled",
                    "locations": [
                        {"locationName": "eastus", "failoverPriority": 0, "isZoneRedundant": True},
                        {"locationName": "westus", "failoverPriority": 1},
                    ],
                }
            },
        ),
        ("azurerm_cosmosdb_account", {"geo_location": []}, {"properties": {}}),
        ("azurerm_cosmosdb_account", {"geo_location": ["not an object"]}, {"properties": {}}),
        # aks
        (
            "azurerm_kubernetes_cluster",
            {"private_cluster_enabled": True},
            {"properties": {"apiServerAccessProfile": {"enablePrivateCluster": True}}},
        ),
        (
            "azurerm_kubernetes_cluster",
            {"default_node_pool": [{"name": "system", "zones": ["3", "1"], "node_count": 2}]},
            {"properties": {"agentPoolProfiles": [{"availabilityZones": ["1", "3"], "name": "system", "count": 2}]}},
        ),
        (
            "azurerm_kubernetes_cluster",
            {"default_node_pool": [{"name": "system", "zones": None}]},
            {"properties": {"agentPoolProfiles": [{"availabilityZones": [], "name": "system"}]}},
        ),
        (
            "azurerm_kubernetes_cluster",
            {"default_node_pool": [{"name": "system"}]},
            {"properties": {}},
        ),  # zones unreadable: no pool list
        # public ip, scale sets, virtual machines
        (
            "azurerm_public_ip",
            {"sku": "Standard", "sku_tier": "Global", "zones": ["2", "1"]},
            {"sku": {"name": "Standard", "tier": "Global"}, "zones": ["1", "2"]},
        ),
        ("azurerm_public_ip", {"sku": "Basic", "zones": None}, {"sku": {"name": "Basic"}, "zones": []}),
        (
            "azurerm_linux_virtual_machine_scale_set",
            {"sku": "Standard_D2_v5", "zones": ["1", "2", "3"]},
            {"sku": {"name": "Standard_D2_v5"}, "zones": ["1", "2", "3"]},
        ),
        ("azurerm_windows_virtual_machine", {"zone": "2"}, {"zones": ["2"]}),
        ("azurerm_linux_virtual_machine", {"zone": None}, {"zones": []}),
        # the rest of the table
        (
            "azurerm_key_vault",
            {"public_network_access_enabled": False},
            {"properties": {"publicNetworkAccess": "Disabled"}},
        ),
        (
            "azurerm_container_registry",
            {"sku": "Premium", "public_network_access_enabled": False},
            {"sku": {"name": "Premium"}, "properties": {"publicNetworkAccess": "Disabled"}},
        ),
        (
            "azurerm_servicebus_namespace",
            {"sku": "Standard", "public_network_access_enabled": True},
            {"sku": {"name": "Standard"}, "properties": {"publicNetworkAccess": "Enabled"}},
        ),
        (
            "azurerm_eventhub_namespace",
            {"sku": "Basic", "public_network_access_enabled": True},
            {"sku": {"name": "Basic"}, "properties": {"publicNetworkAccess": "Enabled"}},
        ),
        (
            "azurerm_app_configuration",
            {"sku": "standard", "public_network_access": "Disabled"},
            {"sku": {"name": "standard"}, "properties": {"publicNetworkAccess": "Disabled"}},
        ),
        (
            "azurerm_app_configuration",
            {"sku": "free", "public_network_access": None},
            {"sku": {"name": "free"}, "properties": {}},
        ),  # null: left to Azure ("Automatic")
        (
            "azurerm_cognitive_account",
            {"sku_name": "S0", "public_network_access_enabled": False},
            {"sku": {"name": "S0"}, "properties": {"publicNetworkAccess": "Disabled"}},
        ),
    ],
)
def test_the_table_reads_these_attributes_the_way_resource_graph_names_them(terraform_type, attributes, expected):
    row = row_of_state(terraform_type, attrs(terraform_type, **attributes))
    dumped = row.model_dump()
    for field, value in expected.items():
        assert dumped[field] == value, field


@pytest.mark.parametrize(
    ("terraform_type", "arm_type"),
    [
        ("azurerm_container_app", "microsoft.app/containerapps"),
        ("azurerm_logic_app_workflow", "microsoft.logic/workflows"),
        ("azurerm_data_factory", "microsoft.datafactory/factories"),
        ("azurerm_api_management", "microsoft.apimanagement/service"),
        ("azurerm_machine_learning_workspace", "microsoft.machinelearningservices/workspaces"),
        ("azurerm_cdn_frontdoor_profile", "microsoft.cdn/profiles"),
        ("azurerm_application_gateway", "microsoft.network/applicationgateways"),
        ("azurerm_linux_web_app_slot", "microsoft.web/sites/slots"),
        ("azurerm_windows_web_app_slot", "microsoft.web/sites/slots"),
    ],
)
def test_types_the_detectors_read_only_for_identity_give_identity_tags_and_location(terraform_type, arm_type):
    row = row_of_state(
        terraform_type,
        attrs(
            terraform_type, location="West Europe", identity=[{"type": "SystemAssigned, UserAssigned"}], tags={"a": "b"}
        ),
    )
    assert row.type == arm_type
    assert row.identity == {"type": "SystemAssigned, UserAssigned"} and row.tags == {"a": "b"}
    assert row.location == "westeurope"  # East US 2 or eastus2: Resource Graph spells it without spaces, in lower case
    assert row.properties == {} and row.sku == {} and row.notCarried == []


# --- the three fields that mean "none" in an export ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("identity", "identity_row", "carried"),
    [
        ([], {}, True),  # no identity block: none is assigned
        ([{"type": "SystemAssigned"}], {"type": "SystemAssigned"}, True),
        ([{"type": "UserAssigned", "identity_ids": ["x"]}], {"type": "UserAssigned"}, True),
        (None, {}, False),
        ([{"type": None}], {}, False),
        ([{"identity_ids": []}], {}, False),
        ("SystemAssigned", {}, False),
        ({"type": "SystemAssigned"}, {}, False),
    ],
)
def test_an_identity_is_none_only_when_the_document_says_so(identity, identity_row, carried):
    row = row_of_state("azurerm_linux_web_app", attrs("azurerm_linux_web_app", identity=identity))
    assert row.identity == identity_row
    assert ("identity" not in row.notCarried) is carried


def test_a_type_without_an_identity_attribute_does_not_carry_one():
    key_vault = row_of_state("azurerm_key_vault", attrs("azurerm_key_vault"))
    assert key_vault.identity == {} and key_vault.notCarried == ["identity"]


@pytest.mark.parametrize(
    ("tags", "row_tags", "carried"),
    [
        ({"a": "b"}, {"a": "b"}, True),
        ({}, {}, True),
        (None, {}, True),  # null: the resource has no tags
        ({"n": 1, "z": None}, {"n": "1", "z": ""}, True),
        ("a=b", {}, False),
        (["a"], {}, False),
    ],
)
def test_tags_are_none_only_when_the_document_says_so(tags, row_tags, carried):
    row = row_of_state(
        "azurerm_key_vault", {"id": arm_id("Microsoft.KeyVault", "vaults", "main"), "name": "main", "tags": tags}
    )
    assert row.tags == row_tags and ("tags" not in row.notCarried) is carried


def test_a_type_with_no_tags_attribute_does_not_carry_tags():
    row = row_of_state("azurerm_key_vault", {"id": arm_id("Microsoft.KeyVault", "vaults", "main"), "name": "main"})
    assert row.tags == {} and "tags" in row.notCarried


@pytest.mark.parametrize(
    ("attributes", "zones", "carried"),
    [
        ({"zones": ["2", "1"]}, ["1", "2"], True),
        ({"zones": [1, 2]}, ["1", "2"], True),
        ({"zones": []}, [], True),
        ({"zones": None}, [], True),
        ({}, [], False),  # not in the document: unknown, not "no zones"
        ({"zones": "1,2"}, [], False),
        ({"zones": [True]}, [], False),
        ({"zones": [{"x": 1}]}, [], False),
    ],
)
def test_zones_are_none_only_when_the_document_says_so(attributes, zones, carried):
    row = row_of_state("azurerm_public_ip", attrs("azurerm_public_ip", **attributes))
    assert row.zones == zones and ("zones" not in row.notCarried) is carried


def test_a_virtual_machines_zone_is_one_string_or_null():
    base = attrs("azurerm_linux_virtual_machine")
    assert row_of_state("azurerm_linux_virtual_machine", {**base, "zone": "3"}).zones == ["3"]
    assert row_of_state("azurerm_linux_virtual_machine", {**base, "zone": None}).zones == []
    assert "zones" in row_of_state("azurerm_linux_virtual_machine", base).notCarried
    assert "zones" in row_of_state("azurerm_linux_virtual_machine", {**base, "zone": ["1"]}).notCarried
    assert "zones" not in row_of_state("azurerm_linux_virtual_machine", {**base, "zone": "1"}).notCarried


# --- identity of a row ----------------------------------------------------------------------------------------------


def test_an_azure_id_is_lower_cased_and_gives_the_subscription_and_group():
    rid = (
        "/subscriptions/00000000-0000-0000-0000-00000000000A/resourceGroups/RG-Mixed"
        "/providers/Microsoft.KeyVault/vaults/Vault1"
    )
    row = row_of_state("azurerm_key_vault", {"id": rid, "name": "Vault1", "tags": {}})
    assert row.id == rid.lower() and row.subscriptionId == "00000000-0000-0000-0000-00000000000a"
    assert row.resourceGroup == "RG-Mixed" and row.name == "Vault1"


def test_resource_group_name_wins_over_the_group_in_the_id_and_the_name_falls_back_to_the_id():
    rid = arm_id("Microsoft.KeyVault", "vaults", "v1", group="rg-from-id")
    row = row_of_state("azurerm_key_vault", {"id": rid, "resource_group_name": "rg-attribute", "tags": {}})
    assert row.resourceGroup == "rg-attribute" and row.name == "v1"


@pytest.mark.parametrize("bad_id", [None, "", "not-an-azure-id", "00000000-0000-0000-0000-0000000000ff", 5, ["x"]])
def test_without_an_azure_id_the_row_is_keyed_by_its_terraform_address(bad_id):
    record = state_record("azurerm_key_vault", "vault", {"id": bad_id, "name": "v", "tags": {}}, module="module.shared")
    [row] = rows_of_state(record)
    assert row.id == "terraform:module.shared.azurerm_key_vault.vault" and row.subscriptionId is None


def test_addresses_carry_the_module_and_the_index_key():
    records = [
        state_record("azurerm_key_vault", "counted", {"name": "a"}, index_key=0),
        state_record("azurerm_key_vault", "keyed", {"name": "b"}, index_key='quote"d', module='module.m["x"]'),
    ]
    assert [r.id for r in rows_of_state(*records)] == [
        "terraform:azurerm_key_vault.counted[0]",
        'terraform:module.m["x"].azurerm_key_vault.keyed["quote\\"d"]',
    ]


def test_a_database_inherits_its_servers_location_only_from_a_server_in_the_document():
    server_id = arm_id("Microsoft.Sql", "servers", "srv")
    database = state_record(
        "azurerm_mssql_database",
        "db",
        {"id": server_id + "/databases/db", "name": "db", "server_id": server_id, "tags": {}},
    )
    server = state_record(
        "azurerm_mssql_server", "srv", {"id": server_id, "name": "srv", "location": "West US", "tags": {}}
    )
    assert {r.name: r.location for r in rows_of_state(server, database)} == {"srv": "westus", "db": "westus"}
    assert {r.name: r.location for r in rows_of_state(database)} == {"db": None}


def test_a_node_pool_is_not_a_row_but_joins_its_cluster():
    cluster_id = arm_id("Microsoft.ContainerService", "managedClusters", "aks")
    cluster = state_record(
        "azurerm_kubernetes_cluster",
        "aks",
        {
            "id": cluster_id,
            "name": "aks",
            "tags": {},
            "default_node_pool": [{"name": "system", "zones": ["1"], "node_count": 1}],
        },
    )
    pool = state_record(
        "azurerm_kubernetes_cluster_node_pool",
        "user",
        {
            "id": cluster_id + "/agentPools/user",
            "name": "user",
            "kubernetes_cluster_id": cluster_id.upper(),
            "zones": ["1", "2"],
        },
    )
    result = parse_terraform_state(state_of(cluster, pool))
    [row] = result.resources
    assert [p["name"] for p in row.properties["agentPoolProfiles"]] == ["system", "user"]
    assert result.summary["foldedIn"] == 1 and result.summary["mapped"] == 1


def test_a_pool_that_cannot_be_placed_or_read_leaves_the_pool_list_out_rather_than_short():
    cluster_id = arm_id("Microsoft.ContainerService", "managedClusters", "aks")
    other_id = arm_id("Microsoft.ContainerService", "managedClusters", "other")

    def cluster(name, cluster_id):
        return state_record(
            "azurerm_kubernetes_cluster",
            name,
            {"id": cluster_id, "name": name, "tags": {}, "default_node_pool": [{"name": "system", "zones": ["1"]}]},
        )

    def pool(**more):
        return state_record("azurerm_kubernetes_cluster_node_pool", "p", {"name": "p", "zones": ["1"], **more})

    both = (cluster("aks", cluster_id), cluster("other", other_id))
    placed = parse_terraform_state(state_of(*both, pool(kubernetes_cluster_id=cluster_id))).resources
    assert [bool(r.properties.get("agentPoolProfiles")) for r in placed] == [True, True]
    assert len(placed[0].properties["agentPoolProfiles"]) == 2 and len(placed[1].properties["agentPoolProfiles"]) == 1
    # its cluster is unknown until apply: it could be any of them
    unplaced = parse_terraform_state(state_of(*both, pool())).resources
    assert all("agentPoolProfiles" not in r.properties for r in unplaced)
    # its zones are unreadable: only the cluster it names loses the list
    unreadable = parse_terraform_state(state_of(*both, pool(kubernetes_cluster_id=cluster_id, zones="1"))).resources
    assert ["agentPoolProfiles" in r.properties for r in unreadable] == [False, True]
    # a cluster this document does not hold is somebody else's
    elsewhere = parse_terraform_state(
        state_of(*both, pool(kubernetes_cluster_id=arm_id("Microsoft.ContainerService", "managedClusters", "x")))
    ).resources
    assert len(elsewhere[0].properties["agentPoolProfiles"]) == 1


# ---------------------------------------------------------------------------------------------------------------------
# What is left out
# ---------------------------------------------------------------------------------------------------------------------


def test_data_sources_unmapped_types_other_providers_and_destroyed_objects_make_no_row():
    key_vault = {"id": arm_id("Microsoft.KeyVault", "vaults", "kv"), "name": "kv", "tags": {}}
    result = parse_terraform_state(
        state_of(
            state_record("azurerm_key_vault", "data_one", key_vault, mode="data"),
            state_record("azurerm_role_assignment", "ra", {"id": "x"}),
            state_record(
                "azurerm_key_vault",
                "other_provider",
                key_vault,
                provider='provider["registry.terraform.io/acme/azurerm"]',
            ),
            state_record("azurerm_key_vault", "no_provider", key_vault, provider=None),
            state_record("azurerm_key_vault", "tainted_old", key_vault, extra_instance={"deposed": "abcd1234"}),
            state_record("azurerm_key_vault", "real", key_vault),
        )
    )
    assert [r.name for r in result.resources] == ["kv"]
    assert result.summary["dataSources"] == 1 and result.summary["destroyed"] == 1
    assert result.summary["unmapped"] == {"azurerm_key_vault": 2, "azurerm_role_assignment": 1}
    assert result.summary["instances"] == 4  # the data source and the deposed object are not instances read


def test_an_aliased_azurerm_provider_is_azurerm():
    aliased = 'provider["registry.terraform.io/hashicorp/azurerm"].other'
    assert (
        len(
            rows_of_state(
                state_record("azurerm_key_vault", "v", {"id": arm_id("A", "b", "c"), "tags": {}}, provider=aliased)
            )
        )
        == 1
    )


def test_unmapped_types_are_named_only_when_they_look_like_terraform_type_names():
    hostile = ["azurerm_" + "x" * 80, "not a type", "with/slash", "", None, 7, "ünïcode_type"]
    result = parse_terraform_state(state_of(*[state_record(t, "n", {"id": "i"}) for t in hostile]))
    assert result.summary["unmapped"] == {"(other)": len(hostile)}


def test_only_the_fifty_most_common_unmapped_types_are_listed():
    records = [state_record(f"azurerm_type_{i:03d}", "n", {"id": "i"}) for i in range(60)]
    summary = parse_terraform_state(state_of(*records)).summary
    assert len(summary["unmapped"]) == 50 and summary["unmappedTypes"] == 60


def test_an_instance_without_attributes_is_unreadable_not_an_error():
    record = state_record("azurerm_key_vault", "v", {"id": arm_id("A", "b", "c"), "tags": {}})
    record["instances"].append({"schema_version": 0, "attributes": None})
    result = parse_terraform_state(state_of(record))
    assert len(result.resources) == 1 and result.summary["unreadable"] == 1


# ---------------------------------------------------------------------------------------------------------------------
# Sensitive values
# ---------------------------------------------------------------------------------------------------------------------

SECRET = "fictional-sensitive-value"


def test_a_sensitive_attribute_is_not_read_and_the_detector_property_stays_absent():
    row = row_of_state(
        "azurerm_storage_account",
        attrs(
            "azurerm_storage_account",
            account_tier="Standard",
            account_replication_type="LRS",
            public_network_access_enabled=False,
        ),
        sensitive=[attr_path("public_network_access_enabled"), attr_path("account_replication_type")],
    )
    assert row.properties == {} and row.sku == {}


def test_a_sensitive_tag_value_keeps_the_tag_but_withholds_the_answer_about_tags():
    row = row_of_state(
        "azurerm_key_vault",
        attrs("azurerm_key_vault", tags={"owner": SECRET, "env": "prod"}),
        sensitive=[attr_path("tags", "owner")],
    )
    assert row.tags == {"env": "prod"} and "tags" in row.notCarried
    assert SECRET not in json.dumps(row.model_dump())


def test_a_sensitive_whole_attribute_and_an_ancestor_cover_what_is_under_them():
    row = row_of_state(
        "azurerm_key_vault", attrs("azurerm_key_vault", tags={"a": SECRET}), sensitive=[attr_path("tags")]
    )
    assert row.tags == {} and "tags" in row.notCarried
    both = row_of_state(
        "azurerm_key_vault",
        attrs("azurerm_key_vault", tags={"a": SECRET}),
        sensitive=[attr_path("tags", "a"), attr_path("tags")],  # the leaf first, then its ancestor
    )
    assert both.tags == {} and "tags" in both.notCarried


def test_a_sensitive_value_inside_a_list_block_is_found_by_its_position():
    cosmos = attrs(
        "azurerm_cosmosdb_account",
        geo_location=[
            {"location": "eastus", "failover_priority": 0, "zone_redundant": True},
            {"location": "westus", "failover_priority": 1, "zone_redundant": False},
        ],
    )
    row = row_of_state("azurerm_cosmosdb_account", cosmos, sensitive=[attr_path("geo_location", 1, "zone_redundant")])
    first, second = row.properties["locations"]
    assert first["isZoneRedundant"] is True and "isZoneRedundant" not in second
    whole_item = row_of_state("azurerm_cosmosdb_account", cosmos, sensitive=[attr_path("geo_location", 0)])
    assert "locations" not in whole_item.properties  # an item that cannot be read voids the list, it is not skipped


def test_an_index_step_may_be_written_with_the_encoded_value_or_the_bare_one():
    steps = [
        [{"type": "get_attr", "value": "tags"}, {"type": "index", "value": {"value": "owner", "type": "string"}}],
        [{"type": "get_attr", "value": "tags"}, {"type": "index", "value": "env"}],
    ]
    row = row_of_state(
        "azurerm_key_vault",
        attrs("azurerm_key_vault", tags={"owner": SECRET, "env": SECRET, "ok": "1"}),
        sensitive=steps,
    )
    assert row.tags == {"ok": "1"}


@pytest.mark.parametrize(
    "sensitive",
    [
        "yes",
        {"type": "get_attr"},
        [[]],
        [["name"]],
        [[{"type": "get_attr", "value": 7}]],
        [[{"type": "index", "value": {"value": True}}]],
        [[{"type": "index", "value": {"value": 1.5}}]],
        [[{"type": "unknown", "value": "x"}]],
        [attr_path(*["a"] * 65)],
    ],
)
def test_markers_that_cannot_be_read_skip_the_instance(sensitive):
    record = state_record("azurerm_key_vault", "v", {"id": arm_id("A", "b", "c"), "tags": {}})
    record["instances"][0]["sensitive_attributes"] = sensitive
    result = parse_terraform_state(state_of(record))
    assert result.resources == [] and result.summary["unreadable"] == 1


def test_no_markers_at_all_is_not_an_error():
    record = state_record("azurerm_key_vault", "v", {"id": arm_id("A", "b", "c"), "tags": {}})
    for value in (None, []):
        record["instances"][0]["sensitive_attributes"] = value
        assert len(parse_terraform_state(state_of(record)).resources) == 1
    del record["instances"][0]["sensitive_attributes"]
    assert len(parse_terraform_state(state_of(record)).resources) == 1


def test_the_summary_counts_what_terraform_marked_but_never_says_what_it_was():
    record = state_record(
        "azurerm_key_vault",
        "v",
        {"id": arm_id("A", "b", "c"), "tags": {}, "secret_field": SECRET, "other_secret": SECRET},
        sensitive=[attr_path("secret_field"), attr_path("other_secret"), attr_path("other_secret")],
    )
    result = parse_terraform_state(state_of(record))
    assert result.summary["sensitiveMarked"] == 2
    assert SECRET not in json.dumps([r.model_dump() for r in result.resources]) + json.dumps(result.summary)


# --- plans mark sensitivity with a mirror of the value ----------------------------------------------------------------


def test_a_plans_after_sensitive_mirror_withholds_the_same_values():
    after = attrs(
        "azurerm_storage_account",
        account_tier="Standard",
        account_replication_type="ZRS",
        public_network_access_enabled=False,
        tags={"owner": SECRET, "env": "prod"},
    )
    row = row_of_plan(
        "azurerm_storage_account",
        after,
        sensitive={"account_replication_type": True, "tags": {"owner": True}},
    )
    assert row.sku == {} and row.properties == {"publicNetworkAccess": "Disabled"}
    assert row.tags == {"env": "prod"} and "tags" in row.notCarried


def test_a_plans_list_mirror_is_read_by_position():
    cosmos = attrs(
        "azurerm_cosmosdb_account",
        geo_location=[
            {"location": "a", "failover_priority": 0, "zone_redundant": True},
            {"location": "b", "failover_priority": 1, "zone_redundant": True},
        ],
    )
    row = row_of_plan("azurerm_cosmosdb_account", cosmos, sensitive={"geo_location": [{}, {"zone_redundant": True}]})
    first, second = row.properties["locations"]
    assert first["isZoneRedundant"] is True and "isZoneRedundant" not in second


@pytest.mark.parametrize(
    "mask",
    [
        {"public_network_access_enabled": {"nested": True}},  # a dictionary mask over a boolean
        {"public_network_access_enabled": [True]},  # a list mask over a boolean
        {"public_network_access_enabled": "yes"},  # not a mask at all
        {"public_network_access_enabled": 7},
        True,  # everything
        "everything",
    ],
)
def test_a_mask_that_does_not_fit_the_value_withholds_it(mask):
    row = row_of_plan(
        "azurerm_key_vault", attrs("azurerm_key_vault", public_network_access_enabled=True), sensitive=mask
    )
    assert "publicNetworkAccess" not in row.properties


@pytest.mark.parametrize("mask", [False, None, {}, {"unrelated": True}, {"public_network_access_enabled": False}])
def test_masks_that_mark_nothing_withhold_nothing(mask):
    row = row_of_plan(
        "azurerm_key_vault", attrs("azurerm_key_vault", public_network_access_enabled=True), sensitive=mask
    )
    assert row.properties == {"publicNetworkAccess": "Enabled"}


# ---------------------------------------------------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------------------------------------------------


def test_a_value_unknown_until_apply_is_absent_from_after_and_so_not_read():
    row = row_of_plan(
        "azurerm_cosmosdb_account", {"name": "c", "tags": {}, "location": "centralus"}, actions=("create",)
    )
    assert row.id == "terraform:azurerm_cosmosdb_account.main" and "publicNetworkAccess" not in row.properties
    assert row.notCarried == ["identity"]


@pytest.mark.parametrize(
    ("actions", "kept"),
    [
        (("no-op",), True),
        (("update",), True),
        (("create",), True),
        (("delete", "create"), True),  # a replacement still exists afterwards
        (("create", "delete"), True),
        (("delete",), False),
        (("forget",), False),
    ],
)
def test_a_plan_makes_a_row_for_what_exists_after_the_change(actions, kept):
    after = {"id": arm_id("A", "b", "c"), "tags": {}} if kept else None
    plan = plan_of(change_entry("azurerm_key_vault", "v", after, actions=actions))
    result = parse_terraform_plan(plan)
    assert len(result.resources) == (1 if kept else 0)
    assert result.summary["destroyed"] == (0 if kept else 1)


def test_the_plan_actions_are_counted_by_word_and_unknown_words_are_other():
    plan = plan_of(
        change_entry("azurerm_key_vault", "a", {"tags": {}}, actions=("create",)),
        change_entry("azurerm_key_vault", "b", {"tags": {}}, actions=("delete", "create")),
        change_entry("azurerm_key_vault", "c", {"tags": {}}, actions=("explode",)),
        change_entry("azurerm_key_vault", "d", {"tags": {}}, actions=()),
    )
    assert parse_terraform_plan(plan).summary["planActions"] == {"create": 1, "delete+create": 1, "other": 2}


def test_plan_entries_for_data_sources_deposed_objects_and_other_providers_make_no_row():
    plan = plan_of(
        change_entry("azurerm_key_vault", "d", {"tags": {}}, mode="data"),
        change_entry("azurerm_key_vault", "old", {"tags": {}}, extra={"deposed": "abc"}),
        change_entry("azurerm_key_vault", "x", {"tags": {}}, provider_name="registry.terraform.io/acme/azurerm"),
        change_entry("azurerm_key_vault", "y", {"tags": {}}, provider_name=None),
        change_entry("azurerm_key_vault", "z", "not an object"),
    )
    result = parse_terraform_plan(plan)
    assert result.resources == []
    assert result.summary["dataSources"] == 1 and result.summary["destroyed"] == 1 and result.summary["unreadable"] == 1
    assert result.summary["unmapped"] == {"azurerm_key_vault": 2}


def test_the_plan_address_is_the_key_of_a_resource_without_an_id():
    plan = plan_of(
        change_entry(
            "azurerm_key_vault", "v", {"name": "v", "tags": {}}, address='module.a["x"].azurerm_key_vault.v[0]'
        )
    )
    assert parse_terraform_plan(plan).resources[0].id == 'terraform:module.a["x"].azurerm_key_vault.v[0]'


def test_planned_values_are_read_through_nested_modules_when_there_are_no_resource_changes():
    def resource(key, **values):
        return {
            "address": key,
            "mode": "managed",
            "type": "azurerm_key_vault",
            "name": key,
            "provider_name": "registry.terraform.io/hashicorp/azurerm",
            "values": values,
        }

    plan = {
        "format_version": "1.0",
        "planned_values": {
            "root_module": {
                "resources": [resource("root", name="r", tags={})],
                "child_modules": [
                    {
                        "address": "module.a",
                        "resources": [resource("a", name="a", tags={})],
                        "child_modules": [
                            {"address": "module.a.module.b", "resources": [resource("b", name="b", tags={})]}
                        ],
                    },
                    {"address": "module.c", "resources": [resource("c", name="c", tags={})]},
                ],
            }
        },
    }
    assert [r.name for r in parse_terraform_plan(plan).resources] == ["r", "a", "b", "c"]


def test_an_empty_plan_has_no_rows_and_a_plan_with_an_empty_change_list_ignores_planned_values():
    assert parse_terraform_plan({"format_version": "1.2", "resource_changes": []}).resources == []
    assert parse_terraform_plan({"format_version": "1.2", "planned_values": {}}).resources == []
    plan = {
        "format_version": "1.2",
        "resource_changes": [],
        "planned_values": {"root_module": {"resources": [{"values": {}}]}},
    }
    assert parse_terraform_plan(plan).resources == []


# ---------------------------------------------------------------------------------------------------------------------
# What is refused
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        [],
        "state",
        None,
        {"resources": []},
        {"version": 3, "resources": []},
        {"version": 5, "resources": []},
        {"version": "4", "resources": []},
        {"version": True, "resources": []},
        {"version": 4.5, "resources": []},
        {"version": 4},
        {"version": 4, "resources": {}},
        {"version": 4, "resources": ["x"]},
        {"version": 4, "resources": [{"instances": {}}]},
        {"version": 4, "resources": [{"instances": ["x"]}]},
        {"format_version": "1.2", "values": {"root_module": {}}},
    ],
)
def test_a_document_that_is_not_a_version_4_state_is_refused_with_a_code_and_no_content(payload):
    with pytest.raises(IngestionError) as exc:
        parse_terraform_state(payload)
    assert exc.value.code == "invalid_request"


def test_the_refusal_of_show_json_output_says_which_kind_to_use():
    with pytest.raises(IngestionError) as exc:
        parse_terraform_state({"format_version": "1.0", "values": {}})
    assert "tf-plan" in str(exc.value)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        "plan",
        {"resource_changes": []},
        {"format_version": "2.0", "resource_changes": []},
        {"format_version": "1", "resource_changes": []},
        {"format_version": "1.x", "resource_changes": []},
        {"format_version": "1.2.3", "resource_changes": []},
        {"format_version": 1.2, "resource_changes": []},
        {"format_version": "1." + "9" * 7, "resource_changes": []},
        {"format_version": "1.2"},
        {"format_version": "1.2", "resource_changes": {}},
        {"format_version": "1.2", "planned_values": []},
        {"format_version": "1.2", "resource_changes": ["x"]},
        {"format_version": "1.2", "resource_changes": [{"type": "t"}]},
        {"format_version": "1.2", "resource_changes": [{"change": {"after": {}, "actions": []}}, 5]},
        {"format_version": "1.2", "planned_values": {"root_module": []}},
        {"format_version": "1.2", "planned_values": {"root_module": {"resources": ["x"]}}},
        {"format_version": "1.2", "planned_values": {"root_module": {"child_modules": ["x"]}}},
    ],
)
def test_a_document_that_is_not_a_1x_plan_is_refused(payload):
    with pytest.raises(IngestionError) as exc:
        parse_terraform_plan(payload)
    assert exc.value.code == "invalid_request"


def test_the_row_limit_applies_to_rows_not_to_everything_the_document_holds():
    records = [
        state_record("azurerm_key_vault", f"v{i}", {"id": arm_id("A", "b", f"c{i}"), "tags": {}}) for i in range(3)
    ]
    unmapped = [state_record("azurerm_role_assignment", f"r{i}", {"id": "x"}) for i in range(10)]
    assert len(parse_terraform_state(state_of(*records, *unmapped), max_rows=3).resources) == 3
    with pytest.raises(IngestionError) as exc:
        parse_terraform_state(state_of(*records, *unmapped), max_rows=2)
    assert exc.value.code == "too_many_rows"
    plan = plan_of(*[change_entry("azurerm_key_vault", f"v{i}", {"tags": {}}) for i in range(3)])
    with pytest.raises(IngestionError) as exc:
        parse_terraform_plan(plan, max_rows=2)
    assert exc.value.code == "too_many_rows"


# ---------------------------------------------------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------------------------------------------------


def nested(depth: int, leaf: Any = 1) -> Any:
    node = leaf
    for _ in range(depth):
        node = [node]
    return node


@pytest.mark.parametrize("depth", [101, 1_000, 200_000])
def test_a_document_nested_too_deeply_is_refused_without_recursion(depth):
    # 200,000 levels would overflow the stack of any recursive walk; the check is iterative
    with pytest.raises(IngestionError) as exc:
        check_json_bounds(nested(depth))
    assert exc.value.code == "too_large" and "deeper" in str(exc.value)


def test_a_document_at_the_depth_limit_is_accepted_and_the_count_of_values_is_exact():
    check_json_bounds(nested(100))
    check_json_bounds({"a": [1, 2, 3], "b": {"c": None}}, max_values=7)  # three containers and four scalars
    with pytest.raises(IngestionError) as exc:
        check_json_bounds({"a": [1, 2, 3], "b": {"c": None}}, max_values=6)
    assert exc.value.code == "too_large" and "values" in str(exc.value)


def test_a_wide_document_is_refused_by_the_number_of_values():
    with pytest.raises(IngestionError) as exc:
        check_json_bounds(list(range(1_001)), max_values=1_000)
    assert exc.value.code == "too_large"
    check_json_bounds([[]] * 5 + [1] * 5, max_values=11)


def test_a_document_that_contains_itself_is_refused():
    loop: list[Any] = []
    loop.append(loop)
    with pytest.raises(IngestionError):
        check_json_bounds(loop)
    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic
    with pytest.raises(IngestionError):
        check_json_bounds(cyclic)


def test_scalars_and_empty_containers_are_within_bounds():
    for value in (1, "text", None, True, [], {}, [[]], {"a": {}}):
        check_json_bounds(value)


def test_both_parsers_check_the_bounds_before_reading_anything():
    deep = state_of(state_record("azurerm_key_vault", "v", {"id": "x", "tags": {}}))
    deep["resources"][0]["instances"][0]["attributes"]["deep"] = nested(150)
    with pytest.raises(IngestionError) as exc:
        parse_terraform_state(deep)
    assert exc.value.code == "too_large"
    plan = plan_of(change_entry("azurerm_key_vault", "v", {"tags": {}, "deep": nested(150)}))
    with pytest.raises(IngestionError) as exc:
        parse_terraform_plan(plan)
    assert exc.value.code == "too_large"


def test_no_regular_expression_runs_over_a_value_in_the_terraform_modules():
    # The values the table names are checked by type and compared as whole words. With no pattern there is nothing that
    # can be made quadratic by a crafted string (the redaction pattern that was, ticket #53, runs before this module).
    for name in ("terraform", "terraform_types"):
        source = (Path(terraform_module.__file__).with_name(f"{name}.py")).read_text(encoding="utf-8")
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Import | ast.ImportFrom)
            for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(name=node.module or "")])
        }
        assert "re" not in imported and "fnmatch" not in imported, name


def _seconds(build, size: int, trials: int = 3) -> float:
    document = build(size)
    best = float("inf")
    for _ in range(trials):
        started = time.perf_counter()
        parse_terraform_state(document)
        best = min(best, time.perf_counter() - started)
    return best


def test_one_enormous_value_costs_time_in_proportion_to_its_length():
    # Two sizes, eight times apart: linear is about 8 (up to about 14 once the string leaves the processor's cache),
    # quadratic about 64. The limit sits between; a result over it is measured again before it fails.
    def build(size: int) -> dict[str, Any]:
        hostile = "eyJ" * (size // 3)
        return state_of(
            state_record(
                "azurerm_key_vault",
                "v",
                {
                    "id": arm_id("A", "b", "c"),
                    "location": hostile,
                    "tags": {hostile: hostile},
                    "public_network_access_enabled": True,
                },
            )
        )

    ratio = float("inf")
    for _ in range(3):
        ratio = min(ratio, _seconds(build, 8_000_000) / _seconds(build, 1_000_000))
        if ratio < 24:
            break
    assert ratio < 24, f"{ratio:.1f}x slower on 8x the text"


# ---------------------------------------------------------------------------------------------------------------------
# Corners
# ---------------------------------------------------------------------------------------------------------------------


def test_a_database_without_a_server_attribute_finds_its_server_through_its_own_id():
    server_id = arm_id("Microsoft.Sql", "servers", "srv")
    database = state_record(
        "azurerm_mssql_database", "db", {"id": server_id + "/databases/db", "name": "db", "tags": {}}
    )
    server = state_record(
        "azurerm_mssql_server", "srv", {"id": server_id, "name": "srv", "location": "eastus", "tags": {}}
    )
    assert {r.name: r.location for r in rows_of_state(server, database)} == {"srv": "eastus", "db": "eastus"}


def test_an_id_without_a_resource_group_gives_none():
    rid = f"/subscriptions/{SUB}/providers/Microsoft.KeyVault/vaults/v"
    [row] = rows_of_state(state_record("azurerm_key_vault", "v", {"id": rid, "tags": {}}))
    assert row.resourceGroup is None and row.subscriptionId == SUB and row.name == "v"


@pytest.mark.parametrize(
    ("index_key", "first", "second"),
    [
        (1.5, "v[0]", "v[1]"),
        (["a"], "v[0]", "v[1]"),
        ({"a": 1}, "v[0]", "v[1]"),
        (True, "v", "v[1]"),  # not a key: treated as no key, the position tells the second from the first
    ],
)
def test_an_index_key_of_an_unexpected_kind_is_replaced_by_the_position(index_key, first, second):
    record = state_record("azurerm_key_vault", "v", {"name": "a"}, index_key=index_key)
    record["instances"].append({"attributes": {"name": "b"}, "index_key": index_key})
    assert [r.id for r in rows_of_state(record)] == [
        f"terraform:azurerm_key_vault.{first}",
        f"terraform:azurerm_key_vault.{second}",
    ]


def test_planned_values_skip_data_sources_and_resources_without_values():
    def resource(key, **more):
        return {
            "address": key,
            "mode": "managed",
            "type": "azurerm_key_vault",
            "name": key,
            "provider_name": "x/hashicorp/azurerm",
            **more,
        }

    plan = {
        "format_version": "1.2",
        "planned_values": {
            "root_module": {
                "resources": [
                    resource("data_one", mode="data", values={"name": "d"}),
                    resource("no_values"),
                    resource("real", values={"name": "r", "tags": {}}),
                ]
            }
        },
    }
    result = parse_terraform_plan(plan)
    assert [r.name for r in result.resources] == ["r"]
    assert result.summary["dataSources"] == 1 and result.summary["unreadable"] == 1


def test_a_plan_entry_without_a_list_of_actions_is_still_read():
    entry = change_entry("azurerm_key_vault", "v", {"name": "v", "tags": {}})
    entry["change"]["actions"] = "create"
    result = parse_terraform_plan(plan_of(entry))
    assert len(result.resources) == 1 and "planActions" not in result.summary


def test_an_ancestor_marked_before_its_descendant_covers_the_descendant():
    row = row_of_state(
        "azurerm_key_vault",
        attrs("azurerm_key_vault", tags={"a": SECRET}),
        sensitive=[attr_path("tags"), attr_path("tags", "a")],  # the ancestor first, then something under it
    )
    assert row.tags == {} and "tags" in row.notCarried


def test_a_mask_for_something_the_document_does_not_hold_changes_nothing():
    row = row_of_state(
        "azurerm_key_vault",
        attrs("azurerm_key_vault", public_network_access_enabled=True, tags={"a": "b"}),
        sensitive=[attr_path("not_in_the_document"), attr_path("tags", "not_a_tag")],
    )
    assert (
        row.properties == {"publicNetworkAccess": "Enabled"}
        and row.tags == {"a": "b"}
        and row.notCarried == ["identity"]
    )


def test_a_position_mask_over_a_dictionary_or_a_name_mask_over_a_list_withholds_the_value():
    # state masks name positions with integers and names with strings; a mix-up is read as "withhold"
    over_dict = row_of_state(
        "azurerm_key_vault", attrs("azurerm_key_vault", tags={"a": "b"}), sensitive=[attr_path("tags", 0)]
    )
    assert over_dict.tags == {} and "tags" in over_dict.notCarried
    cosmos = attrs(
        "azurerm_cosmosdb_account",
        geo_location=[{"location": "a", "failover_priority": 0, "zone_redundant": True}],
    )
    over_list = row_of_state(
        "azurerm_cosmosdb_account", cosmos, sensitive=[attr_path("geo_location", "zone_redundant")]
    )
    assert "locations" not in over_list.properties


def test_an_empty_list_mask_over_a_list_withholds_nothing():
    cosmos = attrs(
        "azurerm_cosmosdb_account",
        geo_location=[{"location": "a", "failover_priority": 0, "zone_redundant": True}],
    )
    row = row_of_plan("azurerm_cosmosdb_account", cosmos, sensitive={"geo_location": []})
    assert row.properties["locations"] == [{"locationName": "a", "failoverPriority": 0, "isZoneRedundant": True}]


def test_the_markers_print_as_themselves():
    from cloud_crawler_core.normalize.terraform_types import MISSING, SENSITIVE

    assert repr(MISSING) == "<missing>" and repr(SENSITIVE) == "<sensitive>"


# ---------------------------------------------------------------------------------------------------------------------
# Documents written by Terraform itself
# ---------------------------------------------------------------------------------------------------------------------

# Written by Terraform 1.16.6 from a configuration of the built-in `terraform_data` resource (no provider, no network,
# no Azure), with a sensitive input, `count`, `for_each` and a child module; identifiers replaced by placeholders. The
# type is not one the table maps, so the point is the shape: what Terraform really writes is accepted, counted and
# withheld.


def real(name: str) -> dict:
    return load(SAMPLES / "terraform" / name)


def test_documents_written_by_terraform_are_accepted_and_counted():
    state = parse_terraform_state(real("terraform-data.state.json"))
    assert state.summary["terraformVersion"] == "1.16.6" and state.summary["formatVersion"] == 4
    assert state.summary["instances"] == 7 and state.summary["unmapped"] == {"terraform_data": 7}
    assert state.summary["sensitiveMarked"] == 1 and state.resources == []
    created = parse_terraform_plan(real("terraform-data.plan-create.json"))
    assert created.summary["formatVersion"] == "1.2" and created.summary["planActions"] == {"create": 7}
    assert created.summary["instances"] == 7 and created.summary["sensitiveMarked"] == 1
    updated = parse_terraform_plan(real("terraform-data.plan-update.json"))
    assert updated.summary["planActions"] == {"no-op": 6, "update": 1} and updated.summary["instances"] == 7


def test_the_planned_values_of_a_real_plan_are_read_when_its_changes_are_removed():
    plan = real("terraform-data.plan-update.json")
    del plan["resource_changes"]
    result = parse_terraform_plan(plan)
    assert result.summary["instances"] == 7 and "planActions" not in result.summary
    assert result.summary["sensitiveMarked"] == 1


def test_the_sensitive_markers_terraform_writes_withhold_the_values_they_mark():
    from cloud_crawler_core.normalize.terraform_types import MISSING, Attrs, sensitive_mask_from_state

    by_name = {r["name"]: r for r in real("terraform-data.state.json")["resources"]}
    secret = by_name["sens"]["instances"][0]
    assert secret["sensitive_attributes"] == [[{"type": "get_attr", "value": "input"}]]
    assert (
        Attrs(secret["attributes"], sensitive_mask_from_state(secret["sensitive_attributes"])).get("input") is MISSING
    )
    plain = by_name["plain"]["instances"][0]
    readable = Attrs(plain["attributes"], sensitive_mask_from_state(plain["sensitive_attributes"]))
    assert readable.get("input")["value"]["name"] == "fictional-a"

    changes = {c["address"]: c["change"] for c in real("terraform-data.plan-create.json")["resource_changes"]}
    withheld = changes["terraform_data.sens"]
    assert withheld["after_sensitive"] == {"input": True}
    assert Attrs(withheld["after"], withheld["after_sensitive"]).get("input") is MISSING
    listed = changes["terraform_data.plain"]
    assert Attrs(listed["after"], listed["after_sensitive"]).get("input")["list"] == ["x", "y"]
