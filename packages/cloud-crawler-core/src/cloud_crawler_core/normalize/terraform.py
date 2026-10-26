"""Terraform state and plan -> NormalizedResource rows, so the detectors that read Resource Graph exports read
Terraform too.

Two documents are read, each a JSON object a person or a pipeline already has:

* `tf-state`: a Terraform state file, version 4 (`terraform.tfstate`, or `terraform state pull`): `resources[]`, each
  with `instances[]`, each with `attributes` and the paths Terraform marked sensitive in `sensitive_attributes`.
* `tf-plan`: the JSON of a plan (`terraform show -json plan.out`), `format_version` 1.x. A row is made for each entry of
  `resource_changes[]` that still exists after the change, from `change.after`, with `change.after_sensitive` marking
  what is withheld; a value that is unknown until apply is absent from `after`, so it stays unknown. When a plan has no
  `resource_changes`, the same is read from `planned_values`. A plan describes what Terraform would build, not what
  exists, and the row says nothing more than that.

Rules, all of them about not saying more than the document says:

* What Terraform marks sensitive is withheld before any value is read, and only the values the type table names are
  copied, so nothing else reaches the stored row. A mark that cannot be read skips the instance.
* A Terraform type the table does not know, a data source, a provider other than hashicorp/azurerm and an object that
  is being destroyed make no row; they are counted by Terraform type name in the summary, never listed by content.
* A property the document cannot answer is absent, so the detector that reads it answers `unknown` and names it.
* The document is bounded before anything walks it (depth and number of values), and the rows by `max_rows`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from cloud_crawler_core.models import NormalizedResource
from cloud_crawler_core.normalize.resource_graph import DEFAULT_MAX_ROWS, IngestionError
from cloud_crawler_core.normalize.terraform_types import (
    NODE_POOL_TYPE,
    TYPE_TABLE,
    Attrs,
    Built,
    Unreadable,
    as_str,
    common_fields,
    count_marks,
    pool_profile,
    resource_from,
    sensitive_mask_from_state,
)

STATE_VERSION = 4
MAX_DEPTH = 100  # nesting of the whole document; a real state or plan is under 40
MAX_VALUES = 1_000_000  # values in the whole document; a 5 MB upload cannot hold more than about 2.5 million
MAX_ADDRESS = 512
MAX_LISTED_TYPES = 50  # unmapped Terraform types named in the summary
MAX_NAME = 64

ARM_ID_PREFIX = "/subscriptions/"
ADDRESS_ID_PREFIX = "terraform:"
PLAN_ACTIONS = frozenset({"create", "update", "delete", "no-op", "read", "forget"})


@dataclass
class TerraformEvidence:
    """The rows, and a content-free summary of what was and was not read (counts and Terraform type names only)."""

    resources: list[NormalizedResource]
    summary: dict[str, Any]


# ---------------------------------------------------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------------------------------------------------


def check_json_bounds(value: Any, *, max_depth: int = MAX_DEPTH, max_values: int = MAX_VALUES) -> None:
    """Refuse a document nested deeper than `max_depth` or holding more than `max_values` values. Iterative, so the
    check itself cannot be made to recurse, and run before anything that does (hashing, redaction) touches the document.
    Raises IngestionError with code `too_large`."""
    seen = 0
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            children: Any = node.values()
        elif isinstance(node, list | tuple):
            children = node
        else:
            children = ()  # a scalar at the top of the document
        if children and depth > max_depth:
            raise IngestionError("too_large", f"the document is nested deeper than {max_depth} levels")
        containers = [child for child in children if isinstance(child, dict | list | tuple)]
        seen += 1 + len(children) - len(containers)  # this node and its scalar children; containers count when popped
        if seen > max_values:
            raise IngestionError("too_large", f"the document holds more than {max_values} values")
        stack.extend((child, depth + 1) for child in containers)


# ---------------------------------------------------------------------------------------------------------------------
# Reading the two documents
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class _Instance:
    address: str
    terraform_type: str
    terraform_name: str
    azurerm: bool
    attributes: dict[str, Any]
    mask: Any


@dataclass
class _Collector:
    source: str
    max_rows: int
    default_subscription: str | None = None
    rows: list[NormalizedResource] = field(default_factory=list)
    parents: list[str | None] = field(default_factory=list)  # the parent id of each row, same order
    pool_rows: list[int] = field(default_factory=list)  # positions of the AKS cluster rows
    default_pools: dict[int, list[dict[str, Any]] | None] = field(default_factory=dict)
    node_pools: list[tuple[str | None, dict[str, Any] | None]] = field(default_factory=list)
    unmapped: dict[str, int] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    not_carried: dict[str, int] = field(default_factory=dict)
    actions: dict[str, int] = field(default_factory=dict)
    marked: int = 0

    def count(self, key: str, by: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + by

    def note_unmapped(self, terraform_type: Any, by: int = 1) -> None:
        label = terraform_type if _is_type_name(terraform_type) else "(other)"
        self.unmapped[label] = self.unmapped.get(label, 0) + by

    def add(self, instance: _Instance) -> None:
        self.count("instances")
        self.marked += count_marks(instance.mask)
        if not instance.azurerm:
            self.note_unmapped(instance.terraform_type)
            return
        if instance.terraform_type == NODE_POOL_TYPE:
            self._add_node_pool(Attrs(instance.attributes, instance.mask))
            return
        mapping = TYPE_TABLE.get(instance.terraform_type)
        if mapping is None:
            self.note_unmapped(instance.terraform_type)
            return
        attrs = Attrs(instance.attributes, instance.mask)
        built = Built()
        fields = common_fields(attrs, built)
        if mapping.extra is not None:
            mapping.extra(attrs, built)
        resource_id = as_str(attrs.get("id"))
        if resource_id is not None and resource_id.lower().startswith(ARM_ID_PREFIX):
            row_id = resource_id.lower()
            subscription = _segment(resource_id, "subscriptions")
            if "resourceGroup" not in fields:
                group = _segment(resource_id, "resourceGroups")
                if group is not None:
                    fields["resourceGroup"] = group
            name = as_str(attrs.get("name")) or row_id.rsplit("/", 1)[-1]
            parent = built.parent
            if parent is None and "/databases/" in row_id:
                parent = row_id.split("/databases/", 1)[0]
        else:
            row_id = ADDRESS_ID_PREFIX + instance.address
            subscription = self.default_subscription  # what the caller said the document is about, else unknown
            name = as_str(attrs.get("name")) or instance.terraform_name
            parent = built.parent
            self.count("withoutAzureId")
        resource = resource_from(
            row_id, mapping.arm_type, name, fields, built, subscription.lower() if subscription else None
        )
        self.rows.append(resource)
        self.parents.append(parent)
        for item in resource.notCarried:
            self.not_carried[item] = self.not_carried.get(item, 0) + 1
        if mapping.arm_type == "microsoft.containerservice/managedclusters":
            self.pool_rows.append(len(self.rows) - 1)
            self.default_pools[len(self.rows) - 1] = built.pools
        if len(self.rows) > self.max_rows:
            raise IngestionError("too_many_rows", f"the document yields more than {self.max_rows} resources")

    def _add_node_pool(self, attrs: Attrs) -> None:
        cluster = as_str(attrs.get("kubernetes_cluster_id"))
        profile = pool_profile(attrs.get("name"), attrs.get("zones"), attrs.get("node_count"))
        self.node_pools.append((cluster.lower() if cluster else None, profile))
        self.count("foldedIn")

    def finish(self, header: dict[str, Any]) -> TerraformEvidence:
        self._join_node_pools()
        self._inherit_locations()
        listed = dict(sorted(self.unmapped.items(), key=lambda item: (-item[1], item[0]))[:MAX_LISTED_TYPES])
        summary: dict[str, Any] = {
            "source": self.source,
            **header,
            "instances": self.counts.get("instances", 0),
            "mapped": len(self.rows),
            "foldedIn": self.counts.get("foldedIn", 0),
            "withoutAzureId": self.counts.get("withoutAzureId", 0),
            "dataSources": self.counts.get("dataSources", 0),
            "unreadable": self.counts.get("unreadable", 0),
            "destroyed": self.counts.get("destroyed", 0),
            "unmapped": listed,
            "unmappedTypes": len(self.unmapped),
            "notCarried": dict(sorted(self.not_carried.items())),
            "sensitiveMarked": self.marked,
        }
        if self.actions:
            summary["planActions"] = dict(sorted(self.actions.items()))
        return TerraformEvidence(self.rows, summary)

    def _join_node_pools(self) -> None:
        """A cluster row lists every pool, as Resource Graph does: the default pool plus the node pool resources that
        name the cluster. If a pool cannot be placed (its cluster is unknown until apply) or read (its zones are), the
        pools of the clusters it might belong to are left out, so the zone detector answers unknown, not a count."""
        by_id = {self.rows[position].id: position for position in self.pool_rows}
        extra: dict[int, list[dict[str, Any]]] = {}
        poisoned: set[int] = set()
        for cluster, profile in self.node_pools:
            position = by_id.get(cluster) if cluster else None
            if cluster is None:
                poisoned.update(self.pool_rows)  # it could belong to any cluster in the document
            elif position is None:
                continue  # a cluster Terraform manages elsewhere
            elif profile is None:
                poisoned.add(position)
            else:
                extra.setdefault(position, []).append(profile)
        for position in self.pool_rows:
            default = self.default_pools.get(position)
            if default is None or position in poisoned:
                continue
            self.rows[position].properties["agentPoolProfiles"] = default + extra.get(position, [])

    def _inherit_locations(self) -> None:
        """A database lives in its server's region, whatever its own attributes say; take the server's location when the
        database has none (the database resource has no location attribute)."""
        locations = {row.id: row.location for row in self.rows if row.type == "microsoft.sql/servers" and row.location}
        for row, parent in zip(self.rows, self.parents, strict=True):
            if row.type == "microsoft.sql/servers/databases" and row.location is None and parent in locations:
                row.location = locations[parent]


def _is_type_name(value: Any) -> bool:
    return (
        isinstance(value, str) and 0 < len(value) <= MAX_NAME and value.isascii() and value.replace("_", "").isalnum()
    )


def _segment(resource_id: str, marker: str) -> str | None:
    parts = resource_id.split("/")
    lowered = [part.lower() for part in parts]
    try:
        index = lowered.index(marker.lower())
    except ValueError:
        return None
    return parts[index + 1] if index + 1 < len(parts) and parts[index + 1] else None


def _text(value: Any, limit: int) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= limit else None


def _version_text(value: Any) -> str | None:
    """A Terraform version such as 1.9.5 or 1.10.0-beta1, or None; only these characters are kept."""
    if isinstance(value, str) and 0 < len(value) <= 32 and all(c.isalnum() or c in ".-+" for c in value):
        return value
    return None


def _subscription_text(value: str | None) -> str | None:
    return value.lower() if isinstance(value, str) and 0 < len(value) <= 64 else None


def _bad(message: str) -> IngestionError:
    return IngestionError("invalid_request", message)


def _azurerm_state(provider: Any) -> bool:
    # provider["registry.terraform.io/hashicorp/azurerm"], with .alias after it for an aliased configuration
    return isinstance(provider, str) and 'provider["' in provider and '/hashicorp/azurerm"' in provider


def _azurerm_plan(provider_name: Any) -> bool:
    return isinstance(provider_name, str) and provider_name.endswith("/hashicorp/azurerm")


def parse_terraform_state(
    payload: Any, *, max_rows: int = DEFAULT_MAX_ROWS, default_subscription: str | None = None
) -> TerraformEvidence:
    """Rows from a Terraform state of version 4. A row whose Azure id is unknown takes `default_subscription` (the
    subscription the caller declared the document to be about) for its subscription, and has none without it. Raises
    IngestionError (`invalid_request`, `too_many_rows`, `too_large`) with a message that names no content."""
    if not isinstance(payload, dict):
        raise _bad("a Terraform state is a JSON object")
    version = payload.get("version")
    if isinstance(version, bool) or version != STATE_VERSION:
        hint = (
            " (this looks like `terraform show -json` output: send a plan as tf-plan, or the state file itself)"
            if "format_version" in payload
            else ""
        )
        raise _bad(f"a Terraform state of version {STATE_VERSION} is expected{hint}")
    resources = payload.get("resources")
    if not isinstance(resources, list):
        raise _bad("a Terraform state has a resources array")
    check_json_bounds(payload)
    collector = _Collector("tf-state", max_rows, _subscription_text(default_subscription))
    for index, record in enumerate(resources):
        if not isinstance(record, dict):
            raise _bad(f"resource {index} is not an object")
        instances = record.get("instances")
        if not isinstance(instances, list):
            raise _bad(f"resource {index} has no instances array")
        if record.get("mode") == "data":
            collector.count("dataSources", len(instances))
            continue
        terraform_type = record.get("type")
        name = _text(record.get("name"), MAX_NAME) or ""
        azurerm = _azurerm_state(record.get("provider"))
        module = record.get("module")
        prefix = f"{module}." if _text(module, MAX_ADDRESS) else ""
        for position, instance in enumerate(instances):
            if not isinstance(instance, dict):
                raise _bad(f"resource {index} has an instance that is not an object")
            if instance.get("deposed"):
                collector.count("destroyed")
                continue
            attributes = instance.get("attributes")
            if not isinstance(attributes, dict):
                collector.count("unreadable")
                continue
            try:
                mask = sensitive_mask_from_state(instance.get("sensitive_attributes"))
            except Unreadable:
                collector.count("unreadable")
                continue
            collector.add(
                _Instance(
                    address=_state_address(prefix, terraform_type, name, instance.get("index_key"), position),
                    terraform_type=terraform_type if isinstance(terraform_type, str) else "",
                    terraform_name=name,
                    azurerm=azurerm,
                    attributes=attributes,
                    mask=mask,
                )
            )
    header = {"formatVersion": STATE_VERSION, "terraformVersion": _version_text(payload.get("terraform_version"))}
    return collector.finish(header)


def _state_address(prefix: str, terraform_type: Any, name: str, index_key: Any, position: int) -> str:
    base = f"{prefix}{terraform_type if isinstance(terraform_type, str) else '?'}.{name or '?'}"
    if isinstance(index_key, bool) or index_key is None:
        suffix = f"[{position}]" if position else ""
    elif isinstance(index_key, int):
        suffix = f"[{index_key}]"
    elif isinstance(index_key, str):
        suffix = "[" + json.dumps(index_key[:64], ensure_ascii=True) + "]"
    else:
        suffix = f"[{position}]"
    return (base + suffix)[:MAX_ADDRESS]


def parse_terraform_plan(
    payload: Any, *, max_rows: int = DEFAULT_MAX_ROWS, default_subscription: str | None = None
) -> TerraformEvidence:
    """Rows from the JSON of a Terraform plan (`terraform show -json`), `format_version` 1.x. A row whose Azure id is
    unknown (a resource the plan creates) takes `default_subscription`, as for a state. Raises IngestionError
    (`invalid_request`, `too_many_rows`, `too_large`) with a message that names no content."""
    if not isinstance(payload, dict):
        raise _bad("a Terraform plan is a JSON object")
    format_version = payload.get("format_version")
    major, _, minor = format_version.partition(".") if isinstance(format_version, str) else ("", "", "")
    if len(minor) > 6 or major != "1" or not minor.isdigit():
        raise _bad("a Terraform plan with format_version 1.x is expected (the JSON of `terraform show -json`)")
    changes, planned = payload.get("resource_changes"), payload.get("planned_values")
    if changes is None and planned is None:
        raise _bad("a Terraform plan has resource_changes or planned_values")
    if (changes is not None and not isinstance(changes, list)) or (
        planned is not None and not isinstance(planned, dict)
    ):
        raise _bad("a Terraform plan has resource_changes as an array and planned_values as an object")
    check_json_bounds(payload)
    collector = _Collector("tf-plan", max_rows, _subscription_text(default_subscription))
    if isinstance(changes, list):
        for index, change in enumerate(changes):
            _read_resource_change(collector, index, change)
    elif isinstance(planned, dict):
        _read_planned_values(collector, planned)
    header = {"formatVersion": format_version, "terraformVersion": _version_text(payload.get("terraform_version"))}
    return collector.finish(header)


def _read_resource_change(collector: _Collector, index: int, change: Any) -> None:
    if not isinstance(change, dict):
        raise _bad(f"resource_changes entry {index} is not an object")
    body = change.get("change")
    if not isinstance(body, dict):
        raise _bad(f"resource_changes entry {index} has no change object")
    if change.get("mode") == "data":
        collector.count("dataSources")
        return
    actions = body.get("actions")
    if isinstance(actions, list):
        label = "+".join(a for a in actions if isinstance(a, str) and a in PLAN_ACTIONS) or "other"
        collector.actions[label] = collector.actions.get(label, 0) + 1
    if change.get("deposed"):
        collector.count("destroyed")
        return
    after = body.get("after")
    if after is None:
        collector.count("destroyed")  # deleted (or forgotten): there is nothing after the change
        return
    if not isinstance(after, dict):
        collector.count("unreadable")
        return
    terraform_type = change.get("type")
    collector.add(
        _Instance(
            address=_text(change.get("address"), MAX_ADDRESS) or f"{terraform_type}.{change.get('name')}",
            terraform_type=terraform_type if isinstance(terraform_type, str) else "",
            terraform_name=_text(change.get("name"), MAX_NAME) or "",
            azurerm=_azurerm_plan(change.get("provider_name")),
            attributes=after,
            mask=body.get("after_sensitive"),
        )
    )


def _read_planned_values(collector: _Collector, planned: dict[str, Any]) -> None:
    root = planned.get("root_module")
    if root is None:
        return
    stack: list[Any] = [root]
    while stack:
        module = stack.pop()
        if not isinstance(module, dict):
            raise _bad("planned_values has a module that is not an object")
        for resource in module.get("resources") or []:
            if not isinstance(resource, dict):
                raise _bad("planned_values has a resource that is not an object")
            if resource.get("mode") == "data":
                collector.count("dataSources")
                continue
            values = resource.get("values")
            if not isinstance(values, dict):
                collector.count("unreadable")
                continue
            terraform_type = resource.get("type")
            collector.add(
                _Instance(
                    address=_text(resource.get("address"), MAX_ADDRESS) or f"{terraform_type}.{resource.get('name')}",
                    terraform_type=terraform_type if isinstance(terraform_type, str) else "",
                    terraform_name=_text(resource.get("name"), MAX_NAME) or "",
                    azurerm=_azurerm_plan(resource.get("provider_name")),
                    attributes=values,
                    mask=resource.get("sensitive_values"),
                )
            )
        children = module.get("child_modules")
        if isinstance(children, list):
            stack.extend(reversed(children))
