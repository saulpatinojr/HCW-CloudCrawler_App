"""Limits and refusals of the Terraform normalisers (ticket #54, review findings F2, F3, F7, F8 and F9).

F2: node pools are not rows, so `max_rows` did not bound them, and each one that could not be placed poisoned every
cluster again: cost proportional to pools times clusters. 5,000 clusters and 160,000 pools (3 MiB of JSON) took 10 s
with the interpreter's lock held.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest
from cloud_crawler_core.ingest import ingest
from cloud_crawler_core.models import EvidenceClass, EvidenceKind, ScopeKind, SourceProvenance, SourceType, Subject
from cloud_crawler_core.normalize import IngestionError, parse_terraform_plan, parse_terraform_state
from core_fixtures import NOW
from terraform_fixtures import PROVIDER, SUB, arm_id, change_entry, plan_of, state_of, state_record

SCOPE = Subject(scope=ScopeKind.SUBSCRIPTION, subscriptionId=SUB)
UPLOAD = SourceProvenance(sourceType=SourceType.UPLOAD, artifactName="document.json")
MAX_RATIO = 24.0  # linear is 8 to 14 for 8 times the input (cache effects), quadratic about 55 to 64


def take(kind: EvidenceKind, payload: Any, **kwargs: Any):
    return ingest(
        kind=kind,
        evidence_class=EvidenceClass.IMPORTED,
        payload=payload,
        subject=SCOPE,
        provenance=UPLOAD,
        authenticated=False,
        now=NOW,
        **kwargs,
    )


def best_seconds(call: Callable[[], object], trials: int = 3) -> float:
    best = float("inf")
    for _ in range(trials):
        started = time.perf_counter()
        call()
        best = min(best, time.perf_counter() - started)
    return best


def growth(build: Callable[[int], Callable[[], object]], small: int, large: int, attempts: int = 3) -> float:
    """How many times longer the call takes for `large` than for `small`; a result over the limit is measured again
    and the smallest counts, because noise does not repeat and a quadratic cost does."""
    ratio = float("inf")
    for _ in range(attempts):
        ratio = min(ratio, best_seconds(build(large)) / best_seconds(build(small)))
        if ratio < MAX_RATIO:
            break
    return ratio


# --- F2: node pools -------------------------------------------------------------------------------------------------


def empty_instances(terraform_type: str, name: str, count: int) -> dict[str, Any]:
    return {
        "mode": "managed",
        "type": terraform_type,
        "name": name,
        "provider": PROVIDER,
        "instances": [{"attributes": {}} for _ in range(count)],
    }


def clusters_and_pools(clusters: int, pools: int) -> dict[str, Any]:
    return state_of(
        empty_instances("azurerm_kubernetes_cluster", "c", clusters),
        empty_instances("azurerm_kubernetes_cluster_node_pool", "p", pools),
    )


def test_unplaceable_node_pools_cost_time_in_proportion_to_the_size_of_the_document():
    # Scaling both the clusters and the pools by 8 multiplies a pools-times-clusters cost by 64 and a linear one by 8.
    # The sizes are chosen so that, before the fix, the product dominates: about 36 ms at 1,000 clusters and 4,000
    # pools, 2.3 s at 8,000 and 32,000.
    def build(factor: int) -> Callable[[], object]:
        document = clusters_and_pools(1_000 * factor, 4_000 * factor)
        return lambda: parse_terraform_state(document, max_rows=100_000)

    ratio = growth(build, 1, 8)
    assert ratio < MAX_RATIO, f"{ratio:.1f}x slower on 8 times the clusters and 8 times the pools"


def test_node_pools_count_against_the_row_limit_together_with_the_rows():
    keys = {"id": arm_id("Microsoft.ContainerService", "managedClusters", "aks"), "tags": {}}
    cluster = state_record("azurerm_kubernetes_cluster", "aks", {**keys, "default_node_pool": [{"zones": ["1"]}]})
    pools = empty_instances("azurerm_kubernetes_cluster_node_pool", "p", 5)
    document = state_of(cluster, pools)
    assert len(parse_terraform_state(document, max_rows=6).resources) == 1  # one row and five pools
    with pytest.raises(IngestionError) as exc:
        parse_terraform_state(document, max_rows=5)
    assert exc.value.code == "too_many_rows" and "node pools" in str(exc.value)


def test_node_pools_alone_cannot_exceed_the_row_limit_either():
    with pytest.raises(IngestionError) as exc:
        parse_terraform_state(state_of(empty_instances("azurerm_kubernetes_cluster_node_pool", "p", 11)), max_rows=10)
    assert exc.value.code == "too_many_rows"


def test_a_pool_that_cannot_be_placed_still_leaves_every_pool_list_out():
    clusters = [
        state_record(
            "azurerm_kubernetes_cluster",
            f"c{i}",
            {
                "id": arm_id("Microsoft.ContainerService", "managedClusters", f"c{i}"),
                "default_node_pool": [{"zones": ["1"]}],
            },
        )
        for i in range(3)
    ]
    pools = [state_record("azurerm_kubernetes_cluster_node_pool", f"p{i}", {"zones": ["1"]}) for i in range(4)]
    rows = parse_terraform_state(state_of(*clusters, *pools)).resources
    assert len(rows) == 3 and all("agentPoolProfiles" not in r.properties for r in rows)


# --- F3: hostile text through the whole pipeline ----------------------------------------------------------------------


def hostile_state(size: int) -> dict[str, Any]:
    text = "eyJ" * (size // 3)
    attributes = {"id": arm_id("Microsoft.KeyVault", "vaults", "kv"), "name": "kv", "tags": {"owner": text}}
    return state_of(state_record("azurerm_key_vault", "kv", attributes))


def hostile_plan(size: int) -> dict[str, Any]:
    text = "eyJ" * (size // 3)
    after = {"id": arm_id("Microsoft.KeyVault", "vaults", "kv"), "name": "kv", "tags": {"owner": text}}
    return plan_of(change_entry("azurerm_key_vault", "kv", after))


@pytest.mark.parametrize(
    ("kind", "build"), [(EvidenceKind.TF_STATE, hostile_state), (EvidenceKind.TF_PLAN, hostile_plan)]
)
def test_a_tag_value_of_repeated_eyj_costs_time_in_proportion_to_its_length_through_ingest(kind, build):
    # ingest hashes, redacts (the secret-shape pattern, issue 53) and normalises. This is the whole path.
    def prepare(size: int) -> Callable[[], object]:
        document = build(size)
        return lambda: take(kind, document)

    ratio = growth(prepare, 16_384, 131_072)
    assert ratio < MAX_RATIO, f"{ratio:.1f}x slower on 8x the text (linear is 8 to 14, limit {MAX_RATIO:.0f})"


# --- F7: documents that carry no sensitivity markers -----------------------------------------------------------------


def test_a_state_without_sensitive_attributes_is_counted():
    with_markers = state_record("azurerm_key_vault", "a", {"id": arm_id("A", "b", "c"), "tags": {}})
    without = state_record("azurerm_key_vault", "b", {"id": arm_id("A", "b", "d"), "tags": {}})
    del without["instances"][0]["sensitive_attributes"]
    assert parse_terraform_state(state_of(with_markers)).summary["markersAbsent"] == 0
    assert parse_terraform_state(state_of(with_markers, without)).summary["markersAbsent"] == 1


def test_a_plan_without_after_sensitive_is_counted_and_a_present_empty_mask_is_not():
    present = change_entry("azurerm_key_vault", "a", {"tags": {}})
    absent = change_entry("azurerm_key_vault", "b", {"tags": {}})
    del absent["change"]["after_sensitive"]
    assert parse_terraform_plan(plan_of(present)).summary["markersAbsent"] == 0
    assert parse_terraform_plan(plan_of(present, absent)).summary["markersAbsent"] == 1


def test_planned_values_without_sensitive_values_are_counted():
    base = {"address": "x", "mode": "managed", "type": "azurerm_key_vault", "name": "x"}
    base["provider_name"] = "registry.terraform.io/hashicorp/azurerm"
    plan = {
        "format_version": "1.2",
        "planned_values": {
            "root_module": {
                "resources": [
                    {**base, "values": {"tags": {}}, "sensitive_values": {}},
                    {**base, "address": "y", "values": {"tags": {}}},
                ]
            }
        },
    }
    assert parse_terraform_plan(plan).summary["markersAbsent"] == 1


# --- F8: caps on text taken from the document -------------------------------------------------------------------------


def test_the_address_of_a_plan_entry_without_one_is_built_from_capped_pieces():
    entry = change_entry("azurerm_key_vault", "v", {"name": "v", "tags": {}})
    del entry["address"]
    entry["name"] = "n" * 5_000
    [row] = parse_terraform_plan(plan_of(entry)).resources
    assert len(row.id) <= len("terraform:") + 200 and "n" * 100 not in row.id

    huge_type = change_entry("azurerm_key_vault", "v", {"name": "v", "tags": {}})
    del huge_type["address"]
    huge_type["type"] = "t" * 5_000
    result = parse_terraform_plan(plan_of(huge_type))
    assert result.resources == [] and result.summary["unmapped"] == {"(other)": 1}


def test_the_address_fallback_of_planned_values_is_capped_the_same_way():
    resource = {
        "mode": "managed",
        "type": "azurerm_key_vault",
        "name": "n" * 5_000,
        "provider_name": "registry.terraform.io/hashicorp/azurerm",
        "values": {"name": "v", "tags": {}},
    }
    plan = {"format_version": "1.2", "planned_values": {"root_module": {"resources": [resource]}}}
    [row] = parse_terraform_plan(plan).resources
    assert len(row.id) <= len("terraform:") + 200


def test_a_plan_entry_with_very_many_actions_is_counted_under_one_short_label():
    entry = change_entry("azurerm_key_vault", "v", {"name": "v", "tags": {}})
    entry["change"]["actions"] = ["create"] * 100_000
    labels = parse_terraform_plan(plan_of(entry)).summary["planActions"]
    assert list(labels) == ["other"]
    ordinary = change_entry("azurerm_key_vault", "w", {"name": "w", "tags": {}}, actions=("delete", "create"))
    assert parse_terraform_plan(plan_of(ordinary)).summary["planActions"] == {"delete+create": 1}


# --- F9: documents that cannot be hashed ------------------------------------------------------------------------------


def document_with(value: Any, kind: EvidenceKind) -> dict[str, Any]:
    if kind is EvidenceKind.TF_STATE:
        document = state_of(state_record("azurerm_key_vault", "v", {"id": arm_id("A", "b", "c"), "tags": {}}))
        document["serial"] = value
    else:
        document = plan_of(change_entry("azurerm_key_vault", "v", {"tags": {}}))
        document["terraform_version"] = value
    return document


@pytest.mark.parametrize("kind", [EvidenceKind.TF_STATE, EvidenceKind.TF_PLAN])
@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), -float("inf"), 10**5000, "\ud800", "ok\udc00ok"],
    ids=["nan", "infinity", "negative infinity", "5,000-digit integer", "lone surrogate", "surrogate in text"],
)
def test_values_json_cannot_carry_are_refused_with_a_code_and_without_the_value(kind, value):
    with pytest.raises(IngestionError) as exc:
        take(kind, document_with(value, kind))
    assert exc.value.code == "invalid_request"
    message = str(exc.value)
    assert "\ud800" not in message and "\udc00" not in message and "9" * 10 not in message
