from __future__ import annotations

import pytest
from cloud_crawler_core.normalize import IngestionError, parse_resource_graph_json


def test_parses_portal_shape_and_case_folds(sample_export):
    resources = parse_resource_graph_json(sample_export)
    assert len(resources) == sample_export["count"]
    sql = next(r for r in resources if r.name == "hcw-sample-sql-01")
    assert sql.type == "microsoft.sql/servers/databases"
    assert sql.id.startswith("/subscriptions/00000000-0000-0000-0000-000000000001/resourcegroups/")
    assert sql.resourceGroup == "rg-hcw-sample-prod"
    assert sql.subscriptionId == "00000000-0000-0000-0000-000000000001"
    assert sql.tags["env"] == "prod"
    assert sql.properties["zoneRedundant"] is False


def test_parses_bare_array_and_derives_group_and_subscription_from_id():
    rows = [
        {
            "id": (
                "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/RG-X"
                "/providers/Microsoft.Web/sites/hcw-sample-web"
            ),
            "type": "Microsoft.Web/sites",
            "name": "hcw-sample-web",
            "zones": ["2", "1"],
            "tags": {"n": 1},
        }
    ]
    [r] = parse_resource_graph_json(rows)
    assert r.resourceGroup == "RG-X"
    assert r.subscriptionId == "00000000-0000-0000-0000-000000000001"
    assert r.zones == ["1", "2"]
    assert r.tags == {"n": "1"}
    assert r.location is None and r.sku == {} and r.identity == {} and r.properties == {}


@pytest.mark.parametrize("payload", [{"data": "no"}, "text", 42, {"count": 1}])
def test_rejects_non_exports(payload):
    with pytest.raises(IngestionError) as exc:
        parse_resource_graph_json(payload)
    assert exc.value.code == "invalid_request"


def test_rejects_rows_without_identity():
    with pytest.raises(IngestionError):
        parse_resource_graph_json([{"id": "/x", "type": "t"}])
    with pytest.raises(IngestionError):
        parse_resource_graph_json(["not an object"])


def test_row_limit():
    rows = [{"id": f"/r{i}", "type": "t", "name": f"n{i}"} for i in range(3)]
    with pytest.raises(IngestionError) as exc:
        parse_resource_graph_json(rows, max_rows=2)
    assert exc.value.code == "too_many_rows"
