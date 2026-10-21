"""`zone-redundancy`: is this resource zone redundant? One reader per resource type, each over the Resource Graph
properties that carry the answer. Where the export cannot carry it, the reader says so (`None` with a reason) rather
than guessing. The property names are the ones Resource Graph returns for each type (retrieved 2026-10-21)."""

from __future__ import annotations

from typing import Any

from cloud_crawler_core.detectors.base import Detector, Reading
from cloud_crawler_core.models import NormalizedResource

ZRS_SUFFIXES = ("_ZRS", "_GZRS", "_RAGZRS")


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return None


def sql_database(resource: NormalizedResource, _: dict[str, Any]) -> Reading:
    value = _bool(resource.properties.get("zoneRedundant"))
    if value is None:
        return Reading(None, resource.properties.get("zoneRedundant"), "properties.zoneRedundant is absent")
    return Reading(value, value)


def storage_account(resource: NormalizedResource, _: dict[str, Any]) -> Reading:
    name = resource.sku.get("name")
    if not isinstance(name, str) or not name:
        return Reading(None, name, "sku.name is absent")
    return Reading(name.upper().endswith(ZRS_SUFFIXES), name)


def app_service_plan(resource: NormalizedResource, _: dict[str, Any]) -> Reading:
    value = _bool(resource.properties.get("zoneRedundant"))
    if value is None:
        return Reading(None, resource.properties.get("zoneRedundant"), "properties.zoneRedundant is absent")
    return Reading(value, value)


def postgres_flexible(resource: NormalizedResource, _: dict[str, Any]) -> Reading:
    ha = resource.properties.get("highAvailability")
    mode = ha.get("mode") if isinstance(ha, dict) else None
    if not isinstance(mode, str):
        return Reading(None, mode, "properties.highAvailability.mode is absent")
    return Reading(mode.lower() == "zoneredundant", mode)


def cosmos_account(resource: NormalizedResource, _: dict[str, Any]) -> Reading:
    locations = resource.properties.get("locations")
    if not isinstance(locations, list) or not locations:
        return Reading(None, None, "properties.locations is absent")
    flags = [_bool(loc.get("isZoneRedundant")) if isinstance(loc, dict) else None for loc in locations]
    if any(flag is None for flag in flags):
        return Reading(None, flags, "a location lacks isZoneRedundant")
    return Reading(all(flags), flags)


def aks_cluster(resource: NormalizedResource, parameters: dict[str, Any]) -> Reading:
    minimum = int(parameters.get("minimumZones", 2))
    pools = resource.properties.get("agentPoolProfiles")
    if not isinstance(pools, list) or not pools:
        return Reading(None, None, "properties.agentPoolProfiles is absent")
    counts = []
    for pool in pools:
        zones = pool.get("availabilityZones") if isinstance(pool, dict) else None
        counts.append(len(zones) if isinstance(zones, list) else 0)
    return Reading(all(count >= minimum for count in counts), counts)


def zones_on_resource(resource: NormalizedResource, parameters: dict[str, Any]) -> Reading:
    """Virtual machines are zonal when pinned to any zone; public IP addresses and other zone-spanning resources are
    zone redundant only when they list at least `minimumZones` (default 2)."""
    minimum = int(parameters.get("minimumZones", 1))
    return Reading(len(resource.zones) >= minimum, resource.zones)


def public_ip(resource: NormalizedResource, parameters: dict[str, Any]) -> Reading:
    return zones_on_resource(resource, {"minimumZones": int(parameters.get("minimumZones", 2))})


ZONE_REDUNDANCY = Detector(
    detector_id="zone-redundancy",
    version="1.0.0",
    question="Is the resource zone redundant?",
    readers={
        "microsoft.sql/servers/databases": sql_database,
        "microsoft.storage/storageaccounts": storage_account,
        "microsoft.web/serverfarms": app_service_plan,
        "microsoft.dbforpostgresql/flexibleservers": postgres_flexible,
        "microsoft.documentdb/databaseaccounts": cosmos_account,
        "microsoft.containerservice/managedclusters": aks_cluster,
        "microsoft.compute/virtualmachines": zones_on_resource,
        "microsoft.network/publicipaddresses": public_ip,
    },
)
