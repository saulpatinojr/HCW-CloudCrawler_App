"""`public-access-disabled` and `private-endpoint-present`: the two network-exposure questions of wave one.

Both read the properties Resource Graph returns for each type (retrieved 2026-10-21). `publicNetworkAccess` is the
ARM-wide string `Enabled` / `Disabled`; a few services also return `SecuredByPerimeter`, which means a network
security perimeter governs access and this export cannot say whether the internet reaches the resource, so the
reader answers `unknown` rather than guessing either way. Private endpoints are read from
`privateEndpointConnections`, counting only connections whose state is approved (or carries no state at all, as
some exports omit it).
"""

from __future__ import annotations

from typing import Any

from cloud_crawler_core.detectors.base import Detector, Reading
from cloud_crawler_core.models import NormalizedResource


def _public_network_access(value: Any) -> Reading:
    if not isinstance(value, str) or not value:
        return Reading(None, value, "properties.publicNetworkAccess is absent")
    folded = value.lower()
    if folded == "disabled":
        return Reading(True, value)
    if folded == "enabled":
        return Reading(False, value)
    if folded == "securedbyperimeter":
        return Reading(None, value, "access is governed by a network security perimeter; evaluate the perimeter")
    return Reading(None, value, "properties.publicNetworkAccess carries a value this detector does not know")


def public_network_access(resource: NormalizedResource, _: dict[str, Any]) -> Reading:
    return _public_network_access(resource.properties.get("publicNetworkAccess"))


def postgres_public_network_access(resource: NormalizedResource, _: dict[str, Any]) -> Reading:
    """PostgreSQL flexible servers carry the flag under `properties.network`."""
    network = resource.properties.get("network")
    value = network.get("publicNetworkAccess") if isinstance(network, dict) else None
    reading = _public_network_access(value)
    if reading.answer is None and reading.reason and reading.reason.startswith("properties.publicNetworkAccess"):
        return Reading(None, value, "properties.network.publicNetworkAccess is absent")
    return reading


def aks_private_cluster(resource: NormalizedResource, _: dict[str, Any]) -> Reading:
    """An AKS cluster has no public access when its API server is private."""
    profile = resource.properties.get("apiServerAccessProfile")
    value = profile.get("enablePrivateCluster") if isinstance(profile, dict) else None
    if not isinstance(value, bool):
        return Reading(None, value, "properties.apiServerAccessProfile.enablePrivateCluster is absent")
    return Reading(value, value)


PUBLIC_ACCESS_DISABLED = Detector(
    detector_id="public-access-disabled",
    version="1.0.0",
    question="Is public network access to the resource disabled?",
    readers={
        "microsoft.storage/storageaccounts": public_network_access,
        "microsoft.keyvault/vaults": public_network_access,
        "microsoft.documentdb/databaseaccounts": public_network_access,
        "microsoft.sql/servers": public_network_access,
        "microsoft.dbforpostgresql/flexibleservers": postgres_public_network_access,
        "microsoft.containerregistry/registries": public_network_access,
        "microsoft.servicebus/namespaces": public_network_access,
        "microsoft.eventhub/namespaces": public_network_access,
        "microsoft.appconfiguration/configurationstores": public_network_access,
        "microsoft.cognitiveservices/accounts": public_network_access,
        "microsoft.web/sites": public_network_access,
        "microsoft.containerservice/managedclusters": aks_private_cluster,
    },
)


def private_endpoint_connections(resource: NormalizedResource, _: dict[str, Any]) -> Reading:
    if "privateEndpointConnections" not in resource.properties:
        return Reading(None, None, "properties.privateEndpointConnections is absent from the export")
    connections = resource.properties.get("privateEndpointConnections")
    if not isinstance(connections, list):
        return Reading(None, connections, "properties.privateEndpointConnections is not a list")
    approved = 0
    for connection in connections:
        properties = connection.get("properties", connection) if isinstance(connection, dict) else {}
        state = properties.get("privateLinkServiceConnectionState") if isinstance(properties, dict) else None
        status = state.get("status") if isinstance(state, dict) else None
        if status is None or (isinstance(status, str) and status.lower() == "approved"):
            approved += 1
    return Reading(approved > 0, approved)


def postgres_private_endpoint(resource: NormalizedResource, parameters: dict[str, Any]) -> Reading:
    """A virtual-network-injected flexible server has no private endpoint and needs none; say so."""
    network = resource.properties.get("network")
    if isinstance(network, dict) and network.get("delegatedSubnetResourceId"):
        return Reading(None, "vnet-injected", "the server is injected into a virtual network; no private endpoint")
    return private_endpoint_connections(resource, parameters)


PRIVATE_ENDPOINT_PRESENT = Detector(
    detector_id="private-endpoint-present",
    version="1.0.0",
    question="Does the resource have at least one approved private endpoint connection?",
    readers={
        "microsoft.storage/storageaccounts": private_endpoint_connections,
        "microsoft.keyvault/vaults": private_endpoint_connections,
        "microsoft.documentdb/databaseaccounts": private_endpoint_connections,
        "microsoft.sql/servers": private_endpoint_connections,
        "microsoft.dbforpostgresql/flexibleservers": postgres_private_endpoint,
        "microsoft.containerregistry/registries": private_endpoint_connections,
        "microsoft.servicebus/namespaces": private_endpoint_connections,
        "microsoft.eventhub/namespaces": private_endpoint_connections,
        "microsoft.appconfiguration/configurationstores": private_endpoint_connections,
        "microsoft.cognitiveservices/accounts": private_endpoint_connections,
        "microsoft.web/sites": private_endpoint_connections,
        "microsoft.containerservice/managedclusters": private_endpoint_connections,
    },
)
