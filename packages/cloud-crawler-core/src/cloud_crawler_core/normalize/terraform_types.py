"""The provider-type table: which Terraform resource types the detectors can read, and how each one's attributes become
the properties Azure Resource Graph names.

Only the types and properties the detectors read are mapped, and every mapping is a statement about what Terraform
carries:

* A value is mapped only when the attribute is present and of the expected type. An attribute that is absent from the
  document (it is not in the provider's schema, or a plan cannot know it until apply), null where a null would be a
  guess, of the wrong type, or marked sensitive is left out. The detector that reads the missing property then answers
  `unknown` with the property named. Nothing is defaulted.
* Three fields mean "none" when a Resource Graph export omits them (`identity`, `tags`, `zones`). A Terraform document
  that cannot say what they hold lists them in the row's `notCarried`, so the detectors that read them answer
  `unknown` and not "none". That includes a plan that says the value is unknown until apply (`after_unknown`), and the
  `planned_values` route, which cannot say.
* Only values are copied that the table names; whole blocks are never copied, so an attribute nobody listed cannot
  reach the stored row, secret or not.

Attribute names were read from the azurerm provider documentation for 3.117.1, 4.81.0 and 5.11.0 on 2026-10-26
(`website/docs/r/<type>.html.markdown` in hashicorp/terraform-provider-azurerm at those tags). The names this table
uses are the same in all three, except that the storage account's `public_network_access_enabled` (3.x, 4.x) became
`public_network_access` in 5.x, so both are read. A name that a provider version does not have simply reads as
absent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from cloud_crawler_core.models import NormalizedResource


class _Marker:
    __slots__ = ("label",)

    def __init__(self, label: str) -> None:
        self.label = label

    def __repr__(self) -> str:
        return f"<{self.label}>"


# An attribute that is not in the document: not in the provider's schema, or unknown until apply.
MISSING = _Marker("missing")
# A value Terraform marked sensitive. It replaces the value before any mapper sees the attribute.
SENSITIVE = _Marker("sensitive")


class Unreadable(ValueError):
    """The document's own markers cannot be read, so what is sensitive cannot be told. The instance is skipped."""


# ---------------------------------------------------------------------------------------------------------------------
# Sensitive values
# ---------------------------------------------------------------------------------------------------------------------

MAX_PATH = 64  # the longest sensitive path read; deeper than any attribute of any mapped type


def sensitive_mask_from_state(paths: Any) -> Any:
    """The mask for a state instance's `sensitive_attributes`: a list of paths, each a list of steps such as
    `{"type": "get_attr", "value": "name"}` or `{"type": "index", "value": {"value": 0, "type": "number"}}`. The mask
    is nested dictionaries keyed by attribute name, map key or list position, with True where a value (and everything
    under it) is sensitive. Raises Unreadable when a marker cannot be understood."""
    if paths is None:
        return None
    if not isinstance(paths, list):
        raise Unreadable("sensitive_attributes is not a list")
    root: dict[Any, Any] = {}
    for path in paths:
        if not isinstance(path, list) or not path or len(path) > MAX_PATH:
            raise Unreadable("a sensitive path is malformed")
        node = root
        for position, step in enumerate(path):
            key = _step_key(step)
            if position == len(path) - 1:
                node[key] = True
                break
            child = node.get(key)
            if child is True:
                break  # an ancestor is already sensitive
            if child is None:
                child = node[key] = {}
            node = child
    return root


def _step_key(step: Any) -> str | int:
    if not isinstance(step, dict):
        raise Unreadable("a sensitive path step is malformed")
    kind, value = step.get("type"), step.get("value")
    if kind == "get_attr" and isinstance(value, str):
        return value
    if kind == "index":
        if isinstance(value, dict):
            value = value.get("value")
        if isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool)):
            return value
    raise Unreadable("a sensitive path step is malformed")


def count_marks(mask: Any) -> int:
    """How many values a sensitive mask marks (the True leaves of the nested structure; a mask of True is one)."""
    count = 0
    stack = [mask]
    while stack:
        node = stack.pop()
        if node is True:
            count += 1
        elif isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return count


def scrub(node: Any, mask: Any) -> Any:
    """Replaces every sensitive value of `node` with SENSITIVE, copying only the containers on the way to one. A mask
    that does not fit the value it describes is read as "sensitive": when in doubt, withhold. Recursion is bounded by
    the depth check the document passed before it got here."""
    if mask is True:
        return SENSITIVE
    if mask is False or mask is None or node is None:
        return node
    if isinstance(mask, dict):
        if not mask:
            return node
        if isinstance(node, dict):
            out = dict(node)
            for key, sub in mask.items():
                if not isinstance(key, str):
                    return SENSITIVE  # a position under a dictionary: the mask does not fit
                if key in out:
                    out[key] = scrub(out[key], sub)
            return out
        if isinstance(node, list):
            copy = list(node)
            for key, sub in mask.items():
                if not isinstance(key, int):
                    return SENSITIVE  # a name under a list
                if 0 <= key < len(copy):
                    copy[key] = scrub(copy[key], sub)
            return copy
        return SENSITIVE
    if isinstance(mask, list):
        if not mask:
            return node
        if isinstance(node, list):
            copy = list(node)
            for position, sub in enumerate(mask[: len(copy)]):
                copy[position] = scrub(copy[position], sub)
            return copy
        return SENSITIVE
    return SENSITIVE


class Attrs:
    """The attributes of one resource instance, read through the sensitive mask. `get` returns MISSING when the
    attribute is absent, unknown until apply, or sensitive.

    `unknown` is a plan's `after_unknown`, the mirror of the values with True where one is unknown until apply, which
    `after` leaves out (a map loses the entry, a list keeps its place with null). `partial` is set when the document
    has no such marker at all (`planned_values`), so that nothing can be told to be complete."""

    def __init__(self, values: dict[str, Any], mask: Any, unknown: Any = None, partial: bool = False) -> None:
        self._values = values
        self._mask = mask
        self._unknown = unknown
        self._partial = partial
        self._cache: dict[str, Any] = {}

    def unknown_at(self, name: str) -> bool:
        """True when the plan says something at or under this attribute is unknown until apply, or cannot say."""
        return self._partial or count_marks(_child_mask(self._unknown, name)) > 0

    def identity_unknown(self) -> bool:
        """True when the identity block, an element of it, or its type is unknown. A new resource's `principal_id` and
        `tenant_id` are always unknown until apply and do not matter: the detector reads the type."""
        if self._partial:
            return True
        marks = _child_mask(self._unknown, "identity")
        if marks is None or marks is False:
            return False
        if not isinstance(marks, list):
            return count_marks(marks) > 0
        return any(item is True or (isinstance(item, dict) and count_marks(item.get("type")) > 0) for item in marks)

    def get(self, name: str) -> Any:
        if name not in self._cache:
            value = self._values.get(name, MISSING)
            if value is not MISSING:
                value = scrub(value, _child_mask(self._mask, name))
            self._cache[name] = MISSING if value is SENSITIVE else value
        return self._cache[name]


def _child_mask(mask: Any, name: str) -> Any:
    if mask is None or mask is False:
        return None
    if isinstance(mask, dict):
        return mask.get(name)
    return True  # a mask of any other shape, including True, withholds everything


# ---------------------------------------------------------------------------------------------------------------------
# Typed reads: each returns None when the value is not there in the expected form
# ---------------------------------------------------------------------------------------------------------------------


def as_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def as_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def first_block(value: Any) -> dict[str, Any] | None:
    """The one object of a nested block that holds at most one (`identity`, `default_node_pool`), which Terraform
    writes as a list; a bare object is accepted too."""
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, dict) else None


def zone_name(value: Any) -> str | None:
    """One availability zone as text; None when the value names none: a boolean, a blank string (empty or only
    whitespace) or anything but text or a whole number. A blank string is neither "no zone" nor a zone called "",
    so the caller treats the zone as not carried."""
    if isinstance(value, bool) or not isinstance(value, str | int):
        return None
    text = str(value)
    return text if text.strip() else None


def zone_list(value: Any) -> list[str] | None:
    """Availability zones as sorted strings; null and [] are no zones; None when the value is not a list of
    zones (for example partly unknown, sensitive, or holding a blank name)."""
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    zones: list[str] = []
    for item in value:
        name = zone_name(item)
        if name is None:
            return None
        zones.append(name)
    return sorted(zones)


def access_from_flag(value: Any) -> str | None:
    """`public_network_access_enabled` (a boolean) as the `Enabled` or `Disabled` Resource Graph reports."""
    if isinstance(value, bool):
        return "Enabled" if value else "Disabled"
    return None


def access_from_text(value: Any) -> str | None:
    """`public_network_access` (a string) as Resource Graph spells it; anything else is not read."""
    if isinstance(value, str):
        for known in ("Enabled", "Disabled", "SecuredByPerimeter"):
            if value.lower() == known.lower():
                return known
    return None


# ---------------------------------------------------------------------------------------------------------------------
# What a mapper fills in
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Built:
    """The type-specific part of a row. `parent` is the lower-cased id of the resource this one lives under, used to
    take the parent's location when the child has none of its own."""

    sku: dict[str, Any] = field(default_factory=dict)
    zones: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    not_carried: list[str] = field(default_factory=list)
    parent: str | None = None
    pools: list[dict[str, Any]] | None = None  # AKS: the default node pool, to be joined by the cluster's node pools


Mapper = Callable[[Attrs, Built], None]


@dataclass(frozen=True)
class TypeMapping:
    arm_type: str  # lower-case, as Resource Graph spells it
    extra: Mapper | None = None


def _put(properties: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        properties[key] = value


def _public_access_flag(attrs: Attrs, built: Built, name: str = "public_network_access_enabled") -> None:
    _put(built.properties, "publicNetworkAccess", access_from_flag(attrs.get(name)))


def _public_access_text(attrs: Attrs, built: Built, name: str = "public_network_access") -> None:
    _put(built.properties, "publicNetworkAccess", access_from_text(attrs.get(name)))


def _sku_name(attrs: Attrs, built: Built, attribute: str) -> None:
    name = as_str(attrs.get(attribute))
    if name is not None:
        built.sku = {"name": name}


def _zones_from(attrs: Attrs, built: Built, attribute: str) -> None:
    zones = zone_list(attrs.get(attribute)) if attrs.get(attribute) is not MISSING else None
    if zones is None or attrs.unknown_at(attribute):
        built.not_carried.append("zones")
    if zones is not None:
        built.zones = zones


# --- one mapper per shape ------------------------------------------------------------------------------------------


def _sql_server(attrs: Attrs, built: Built) -> None:
    _public_access_flag(attrs, built)


def _sql_database(attrs: Attrs, built: Built) -> None:
    _sku_name(attrs, built, "sku_name")
    _put(built.properties, "zoneRedundant", as_bool(attrs.get("zone_redundant")))
    server = as_str(attrs.get("server_id"))
    if server is not None:
        built.parent = server.lower()


def _storage_account(attrs: Attrs, built: Built) -> None:
    tier, replication = as_str(attrs.get("account_tier")), as_str(attrs.get("account_replication_type"))
    if tier is not None and replication is not None:
        built.sku = {"name": f"{tier}_{replication}", "tier": tier}
    access = access_from_text(attrs.get("public_network_access"))  # azurerm 5.x
    if access is None:
        access = access_from_flag(attrs.get("public_network_access_enabled"))  # azurerm 3.x and 4.x
    _put(built.properties, "publicNetworkAccess", access)


def _service_plan(attrs: Attrs, built: Built) -> None:
    _sku_name(attrs, built, "sku_name")
    _put(built.properties, "zoneRedundant", as_bool(attrs.get("zone_balancing_enabled")))


def _web_app(attrs: Attrs, built: Built) -> None:
    _public_access_flag(attrs, built)


# The prefix of `sku_name` on a PostgreSQL flexible server is the tier; Resource Graph reports the tier separately.
_POSTGRES_TIERS = {"B": "Burstable", "GP": "GeneralPurpose", "MO": "MemoryOptimized"}


def _postgres_flexible(attrs: Attrs, built: Built) -> None:
    sku = as_str(attrs.get("sku_name"))
    if sku is not None:
        prefix, _, rest = sku.partition("_")
        if rest and prefix in _POSTGRES_TIERS:
            built.sku = {"name": rest, "tier": _POSTGRES_TIERS[prefix]}
    ha = attrs.get("high_availability")
    if isinstance(ha, list):
        if not ha:
            built.properties["highAvailability"] = {"mode": "Disabled"}  # no block: high availability is off
        else:
            mode = as_str(first_block(ha).get("mode")) if first_block(ha) is not None else None
            if mode is not None:
                built.properties["highAvailability"] = {"mode": mode}
    network: dict[str, Any] = {}
    _put(network, "publicNetworkAccess", access_from_flag(attrs.get("public_network_access_enabled")))
    _put(network, "delegatedSubnetResourceId", as_str(attrs.get("delegated_subnet_id")))
    if network:
        built.properties["network"] = network


def _cosmos_account(attrs: Attrs, built: Built) -> None:
    _public_access_flag(attrs, built)
    geo = attrs.get("geo_location")
    if isinstance(geo, list) and geo:
        locations: list[dict[str, Any]] = []
        for item in geo:
            if not isinstance(item, dict):
                locations = []
                break
            entry: dict[str, Any] = {}
            _put(entry, "locationName", as_str(item.get("location")))
            _put(entry, "failoverPriority", as_int(item.get("failover_priority")))
            _put(entry, "isZoneRedundant", as_bool(item.get("zone_redundant")))
            locations.append(entry)
        if locations:
            built.properties["locations"] = locations


def pool_profile(name: Any, zones: Any, count: Any) -> dict[str, Any] | None:
    """One agent pool as Resource Graph spells it; None when its zones cannot be read, because a pool whose zones are
    unknown must not be counted as a pool with none."""
    zone_values = zone_list(zones) if zones is not MISSING else None
    if zone_values is None:
        return None
    profile: dict[str, Any] = {"availabilityZones": zone_values}
    _put(profile, "name", as_str(name))
    _put(profile, "count", as_int(count))
    return profile


def _kubernetes_cluster(attrs: Attrs, built: Built) -> None:
    private = as_bool(attrs.get("private_cluster_enabled"))
    if private is not None:
        built.properties["apiServerAccessProfile"] = {"enablePrivateCluster": private}
    default_pool = first_block(attrs.get("default_node_pool"))
    if default_pool is not None:
        profile = pool_profile(
            default_pool.get("name"), default_pool.get("zones", MISSING), default_pool.get("node_count")
        )
        built.pools = [profile] if profile is not None else None


def _virtual_machine(attrs: Attrs, built: Built) -> None:
    zone = attrs.get("zone")
    if zone is MISSING:
        built.not_carried.append("zones")
    elif zone is None:
        built.zones = []
    elif (name := zone_name(zone)) is not None:
        built.zones = [name]
    else:
        built.not_carried.append("zones")  # a boolean, a blank string, or a value of another type
    if attrs.unknown_at("zone") and "zones" not in built.not_carried:
        built.not_carried.append("zones")


def _scale_set(attrs: Attrs, built: Built) -> None:
    _zones_from(attrs, built, "zones")
    _sku_name(attrs, built, "sku")


def _public_ip(attrs: Attrs, built: Built) -> None:
    _zones_from(attrs, built, "zones")
    sku = as_str(attrs.get("sku"))
    if sku is not None:
        built.sku = {"name": sku}
        tier = as_str(attrs.get("sku_tier"))
        if tier is not None:
            built.sku["tier"] = tier


def _key_vault(attrs: Attrs, built: Built) -> None:
    _public_access_flag(attrs, built)


def _namespace_with_sku(attrs: Attrs, built: Built) -> None:
    _public_access_flag(attrs, built)
    _sku_name(attrs, built, "sku")


def _app_configuration(attrs: Attrs, built: Built) -> None:
    _public_access_text(attrs, built)
    _sku_name(attrs, built, "sku")


def _cognitive_account(attrs: Attrs, built: Built) -> None:
    _public_access_flag(attrs, built)
    _sku_name(attrs, built, "sku_name")


# The azurerm resource that adds a node pool to a cluster. It is not a row of its own: it joins its cluster's
# `agentPoolProfiles`, as Resource Graph lists every pool on the cluster.
NODE_POOL_TYPE = "azurerm_kubernetes_cluster_node_pool"

_SITE = TypeMapping("microsoft.web/sites", _web_app)
_SLOT = TypeMapping("microsoft.web/sites/slots", _web_app)
_VM = TypeMapping("microsoft.compute/virtualmachines", _virtual_machine)
_VMSS = TypeMapping("microsoft.compute/virtualmachinescalesets", _scale_set)

TYPE_TABLE: dict[str, TypeMapping] = {
    "azurerm_mssql_server": TypeMapping("microsoft.sql/servers", _sql_server),
    "azurerm_mssql_database": TypeMapping("microsoft.sql/servers/databases", _sql_database),
    "azurerm_storage_account": TypeMapping("microsoft.storage/storageaccounts", _storage_account),
    "azurerm_service_plan": TypeMapping("microsoft.web/serverfarms", _service_plan),
    "azurerm_linux_web_app": _SITE,
    "azurerm_windows_web_app": _SITE,
    "azurerm_linux_function_app": _SITE,
    "azurerm_windows_function_app": _SITE,
    "azurerm_linux_web_app_slot": _SLOT,
    "azurerm_windows_web_app_slot": _SLOT,
    "azurerm_postgresql_flexible_server": TypeMapping("microsoft.dbforpostgresql/flexibleservers", _postgres_flexible),
    "azurerm_cosmosdb_account": TypeMapping("microsoft.documentdb/databaseaccounts", _cosmos_account),
    "azurerm_kubernetes_cluster": TypeMapping("microsoft.containerservice/managedclusters", _kubernetes_cluster),
    "azurerm_linux_virtual_machine": _VM,
    "azurerm_windows_virtual_machine": _VM,
    "azurerm_linux_virtual_machine_scale_set": _VMSS,
    "azurerm_windows_virtual_machine_scale_set": _VMSS,
    "azurerm_public_ip": TypeMapping("microsoft.network/publicipaddresses", _public_ip),
    "azurerm_key_vault": TypeMapping("microsoft.keyvault/vaults", _key_vault),
    "azurerm_container_registry": TypeMapping("microsoft.containerregistry/registries", _namespace_with_sku),
    "azurerm_servicebus_namespace": TypeMapping("microsoft.servicebus/namespaces", _namespace_with_sku),
    "azurerm_eventhub_namespace": TypeMapping("microsoft.eventhub/namespaces", _namespace_with_sku),
    "azurerm_app_configuration": TypeMapping("microsoft.appconfiguration/configurationstores", _app_configuration),
    "azurerm_cognitive_account": TypeMapping("microsoft.cognitiveservices/accounts", _cognitive_account),
    # types the detectors read only for their identity (and tags and location, which every row carries)
    "azurerm_container_app": TypeMapping("microsoft.app/containerapps"),
    "azurerm_logic_app_workflow": TypeMapping("microsoft.logic/workflows"),
    "azurerm_data_factory": TypeMapping("microsoft.datafactory/factories"),
    "azurerm_api_management": TypeMapping("microsoft.apimanagement/service"),
    "azurerm_machine_learning_workspace": TypeMapping("microsoft.machinelearningservices/workspaces"),
    "azurerm_cdn_frontdoor_profile": TypeMapping("microsoft.cdn/profiles"),
    "azurerm_application_gateway": TypeMapping("microsoft.network/applicationgateways"),
}


# ---------------------------------------------------------------------------------------------------------------------
# The fields every row carries
# ---------------------------------------------------------------------------------------------------------------------


def common_fields(attrs: Attrs, built: Built) -> dict[str, Any]:
    """Location, resource group, identity and tags, which every mapped type has in the same form. Records in
    `built.not_carried` the ones the document cannot answer."""
    fields: dict[str, Any] = {}
    location = as_str(attrs.get("location"))
    if location is not None:
        fields["location"] = location.replace(" ", "").lower()  # East US 2 -> eastus2, as Resource Graph spells it
    group = as_str(attrs.get("resource_group_name"))
    if group is not None:
        fields["resourceGroup"] = group
    identity = attrs.get("identity")
    if isinstance(identity, list):
        if not identity:
            fields["identity"] = {}  # no identity block: none is assigned
        else:
            block = first_block(identity)
            kind = as_str(block.get("type")) if block is not None else None
            if kind is not None:
                fields["identity"] = {"type": kind}
            else:
                built.not_carried.append("identity")
    else:
        built.not_carried.append("identity")  # no identity attribute, or one that is unknown until apply
    if attrs.identity_unknown() and "identity" not in built.not_carried:
        built.not_carried.append("identity")
    tags = attrs.get("tags")
    if tags is None:
        fields["tags"] = {}
    elif isinstance(tags, dict):
        kept: dict[str, str] = {}
        withheld = False
        for key, value in tags.items():
            if value is SENSITIVE:
                withheld = True  # the tag exists but its value is withheld: claims on tags cannot be answered
            else:
                kept[str(key)] = "" if value is None else str(value)
        fields["tags"] = kept
        if withheld:
            built.not_carried.append("tags")
    else:
        built.not_carried.append("tags")
    if attrs.unknown_at("tags") and "tags" not in built.not_carried:
        built.not_carried.append("tags")  # a map that is missing an entry that is only known after apply
    return fields


def resource_from(
    resource_id: str, arm_type: str, name: str, fields: dict[str, Any], built: Built, subscription: str | None
) -> NormalizedResource:
    return NormalizedResource(
        id=resource_id,
        type=arm_type,
        name=name,
        subscriptionId=subscription,
        zones=built.zones,
        sku=built.sku,
        properties=built.properties,
        notCarried=sorted(set(built.not_carried)),
        **fields,
    )
