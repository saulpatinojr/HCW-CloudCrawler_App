from __future__ import annotations

import pytest
from cloud_crawler_core.detectors.network_access import PRIVATE_ENDPOINT_PRESENT, PUBLIC_ACCESS_DISABLED
from cloud_crawler_core.models import NormalizedResource


def resource(rtype: str, **kwargs) -> NormalizedResource:
    base = {
        "id": f"/subscriptions/00000000-0000-0000-0000-000000000001/x/{rtype}",
        "type": rtype,
        "name": "hcw-sample-x",
    }
    base.update(kwargs)
    return NormalizedResource(**base)


@pytest.mark.parametrize(
    ("rtype", "properties", "answer"),
    [
        ("microsoft.storage/storageaccounts", {"publicNetworkAccess": "Disabled"}, True),
        ("microsoft.storage/storageaccounts", {"publicNetworkAccess": "enabled"}, False),
        ("microsoft.storage/storageaccounts", {"publicNetworkAccess": "SecuredByPerimeter"}, None),
        ("microsoft.storage/storageaccounts", {"publicNetworkAccess": "Odd"}, None),
        ("microsoft.storage/storageaccounts", {}, None),
        ("microsoft.keyvault/vaults", {"publicNetworkAccess": "Disabled"}, True),
        ("microsoft.sql/servers", {"publicNetworkAccess": "Enabled"}, False),
        ("microsoft.web/sites", {"publicNetworkAccess": "Disabled"}, True),
        ("microsoft.dbforpostgresql/flexibleservers", {"network": {"publicNetworkAccess": "Disabled"}}, True),
        ("microsoft.dbforpostgresql/flexibleservers", {"network": {"publicNetworkAccess": "Enabled"}}, False),
        ("microsoft.dbforpostgresql/flexibleservers", {"network": {}}, None),
        ("microsoft.dbforpostgresql/flexibleservers", {}, None),
        (
            "microsoft.containerservice/managedclusters",
            {"apiServerAccessProfile": {"enablePrivateCluster": True}},
            True,
        ),
        (
            "microsoft.containerservice/managedclusters",
            {"apiServerAccessProfile": {"enablePrivateCluster": False}},
            False,
        ),
        ("microsoft.containerservice/managedclusters", {}, None),
    ],
)
def test_public_access_readers(rtype, properties, answer):
    reader = PUBLIC_ACCESS_DISABLED.readers[rtype]
    assert reader(resource(rtype, properties=properties), {}).answer is answer


def test_public_access_unknown_reasons_name_the_property():
    r = resource("microsoft.storage/storageaccounts", properties={"publicNetworkAccess": "SecuredByPerimeter"})
    assert "perimeter" in (PUBLIC_ACCESS_DISABLED.readers[r.type](r, {}).reason or "")
    pg = resource("microsoft.dbforpostgresql/flexibleservers", properties={})
    assert PUBLIC_ACCESS_DISABLED.readers[pg.type](pg, {}).reason == "properties.network.publicNetworkAccess is absent"


APPROVED = {"properties": {"privateLinkServiceConnectionState": {"status": "Approved"}}}
PENDING = {"properties": {"privateLinkServiceConnectionState": {"status": "Pending"}}}
FLAT_REJECTED = {"privateLinkServiceConnectionState": {"status": "Rejected"}}


@pytest.mark.parametrize(
    ("properties", "answer", "value"),
    [
        ({"privateEndpointConnections": [APPROVED]}, True, 1),
        ({"privateEndpointConnections": [APPROVED, PENDING]}, True, 1),
        ({"privateEndpointConnections": [PENDING, FLAT_REJECTED]}, False, 0),
        ({"privateEndpointConnections": [{"id": "/pe/1"}]}, True, 1),  # no state in the export: counted
        ({"privateEndpointConnections": []}, False, 0),
        ({"privateEndpointConnections": "x"}, None, "x"),
        ({}, None, None),
    ],
)
def test_private_endpoint_reader(properties, answer, value):
    r = resource("microsoft.storage/storageaccounts", properties=properties)
    reading = PRIVATE_ENDPOINT_PRESENT.readers[r.type](r, {})
    assert reading.answer is answer and reading.value == value


def test_private_endpoint_absent_from_export_is_unknown_with_reason():
    r = resource("microsoft.keyvault/vaults", properties={"publicNetworkAccess": "Disabled"})
    reading = PRIVATE_ENDPOINT_PRESENT.readers[r.type](r, {})
    assert reading.answer is None and "absent from the export" in (reading.reason or "")


def test_postgres_vnet_injected_server_is_unknown_not_contradicted():
    r = resource(
        "microsoft.dbforpostgresql/flexibleservers",
        properties={"network": {"delegatedSubnetResourceId": "/subnets/x"}, "privateEndpointConnections": []},
    )
    reading = PRIVATE_ENDPOINT_PRESENT.readers[r.type](r, {})
    assert reading.answer is None and reading.value == "vnet-injected"
    plain = resource("microsoft.dbforpostgresql/flexibleservers", properties={"privateEndpointConnections": [APPROVED]})
    assert PRIVATE_ENDPOINT_PRESENT.readers[plain.type](plain, {}).answer is True


def test_both_detectors_cover_the_same_types():
    assert PUBLIC_ACCESS_DISABLED.resource_types == PRIVATE_ENDPOINT_PRESENT.resource_types
