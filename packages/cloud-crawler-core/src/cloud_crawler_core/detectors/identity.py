"""`managed-identity`: does the resource run under a managed identity? Read from the top-level `identity.type`
Resource Graph returns (`SystemAssigned`, `UserAssigned`, `SystemAssigned, UserAssigned`, `SystemAssigned,UserAssigned`
or `None`; retrieved 2026-10-21). A resource of a type that supports identities and carries no `identity` block has
none assigned, which is a definite `False`, not an unknown, unless the row lists `identity` in `notCarried` (a
Terraform document that cannot say), which is an unknown. The optional claim parameter `identityType`
(`SystemAssigned` or `UserAssigned`) requires that kind in particular."""

from __future__ import annotations

from typing import Any

from cloud_crawler_core.detectors.base import Detector, Reading, not_carried
from cloud_crawler_core.models import NormalizedResource

KINDS = ("systemassigned", "userassigned")


def identity_type(resource: NormalizedResource, parameters: dict[str, Any]) -> Reading:
    unsaid = not_carried(resource, "identity")
    if unsaid is not None:
        return unsaid
    raw = resource.identity.get("type")
    if raw is not None and not isinstance(raw, str):
        return Reading(None, raw, "identity.type is not a string")
    assigned = {part.strip().lower() for part in (raw or "none").split(",")} & set(KINDS)
    wanted = parameters.get("identityType")
    if wanted is not None:
        folded = str(wanted).replace(" ", "").lower()
        if folded not in KINDS:
            return Reading(None, raw, "identityType must be SystemAssigned or UserAssigned")
        return Reading(folded in assigned, raw or "None")
    return Reading(bool(assigned), raw or "None")


def check_parameters(parameters: dict[str, Any]) -> str | None:
    wanted = parameters.get("identityType")
    if wanted is not None and (not isinstance(wanted, str) or wanted.replace(" ", "").lower() not in KINDS):
        return "identityType must be SystemAssigned or UserAssigned"
    return None


MANAGED_IDENTITY = Detector(
    detector_id="managed-identity",
    version="1.0.0",
    question="Does the resource have a managed identity assigned?",
    parameter_check=check_parameters,
    readers={
        "microsoft.web/sites": identity_type,
        "microsoft.web/sites/slots": identity_type,
        "microsoft.compute/virtualmachines": identity_type,
        "microsoft.compute/virtualmachinescalesets": identity_type,
        "microsoft.containerservice/managedclusters": identity_type,
        "microsoft.app/containerapps": identity_type,
        "microsoft.logic/workflows": identity_type,
        "microsoft.datafactory/factories": identity_type,
        "microsoft.apimanagement/service": identity_type,
        "microsoft.containerregistry/registries": identity_type,
        "microsoft.keyvault/vaults": identity_type,
        "microsoft.storage/storageaccounts": identity_type,
        "microsoft.sql/servers": identity_type,
        "microsoft.documentdb/databaseaccounts": identity_type,
        "microsoft.dbforpostgresql/flexibleservers": identity_type,
        "microsoft.cognitiveservices/accounts": identity_type,
        "microsoft.machinelearningservices/workspaces": identity_type,
        "microsoft.eventhub/namespaces": identity_type,
        "microsoft.servicebus/namespaces": identity_type,
        "microsoft.cdn/profiles": identity_type,
        "microsoft.network/applicationgateways": identity_type,
    },
)
