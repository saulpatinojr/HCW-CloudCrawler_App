"""Builders for small, fictional Terraform state and plan documents, so each test says only what it is about."""

from __future__ import annotations

from typing import Any

from cloud_crawler_core.models import NormalizedResource
from cloud_crawler_core.normalize import parse_terraform_plan, parse_terraform_state

SUB = "00000000-0000-0000-0000-000000000001"
GROUP = "rg-hcw-sample-prod"
PROVIDER = 'provider["registry.terraform.io/hashicorp/azurerm"]'
PROVIDER_NAME = "registry.terraform.io/hashicorp/azurerm"


def arm_id(namespace: str, kind: str, name: str, *more: str, group: str = GROUP) -> str:
    return f"/subscriptions/{SUB}/resourceGroups/{group}/providers/{'/'.join([namespace, kind, name, *more])}"


def attr_path(*steps: str | int) -> list[dict[str, Any]]:
    """A sensitive path as Terraform writes it in a state: `get_attr` for names and map keys, `index` for positions."""
    return [
        {"type": "get_attr", "value": step}
        if isinstance(step, str)
        else {"type": "index", "value": {"value": step, "type": "number"}}
        for step in steps
    ]


def state_record(
    terraform_type: str,
    name: str,
    attributes: dict[str, Any],
    *,
    sensitive: list[list[dict[str, Any]]] | None = None,
    module: str | None = None,
    mode: str = "managed",
    provider: Any = PROVIDER,
    index_key: Any = None,
    extra_instance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    instance: dict[str, Any] = {"schema_version": 0, "attributes": attributes, "sensitive_attributes": sensitive or []}
    if index_key is not None:
        instance["index_key"] = index_key
    instance.update(extra_instance or {})
    record: dict[str, Any] = {"mode": mode, "type": terraform_type, "name": name, "provider": provider}
    if module:
        record["module"] = module
    record["instances"] = [instance]
    return record


def state_of(*records: dict[str, Any], version: Any = 4) -> dict[str, Any]:
    return {"version": version, "terraform_version": "1.9.8", "serial": 1, "lineage": "x", "resources": list(records)}


def change_entry(
    terraform_type: str,
    name: str,
    after: Any,
    *,
    actions: tuple[str, ...] = ("no-op",),
    sensitive: Any = None,
    address: str | None = None,
    provider_name: Any = PROVIDER_NAME,
    mode: str = "managed",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "address": address or f"{terraform_type}.{name}",
        "mode": mode,
        "type": terraform_type,
        "name": name,
        "provider_name": provider_name,
        "change": {
            "actions": list(actions),
            "before": None,
            "after": after,
            "after_unknown": {},
            "before_sensitive": False,
            "after_sensitive": {} if sensitive is None else sensitive,
        },
    }
    entry.update(extra or {})
    return entry


def plan_of(*changes: dict[str, Any], format_version: Any = "1.2") -> dict[str, Any]:
    return {"format_version": format_version, "terraform_version": "1.9.8", "resource_changes": list(changes)}


def rows_of_state(*records: dict[str, Any], **kwargs: Any) -> list[NormalizedResource]:
    return parse_terraform_state(state_of(*records), **kwargs).resources


def row_of_state(terraform_type: str, attributes: dict[str, Any], **kwargs: Any) -> NormalizedResource:
    """The one row a state with a single resource of this type gives."""
    sensitive = kwargs.pop("sensitive", None)
    [row] = rows_of_state(state_record(terraform_type, "main", attributes, sensitive=sensitive), **kwargs)
    return row


def row_of_plan(terraform_type: str, after: dict[str, Any], **kwargs: Any) -> NormalizedResource:
    sensitive = kwargs.pop("sensitive", None)
    actions = kwargs.pop("actions", ("no-op",))
    [row] = parse_terraform_plan(
        plan_of(change_entry(terraform_type, "main", after, sensitive=sensitive, actions=actions)), **kwargs
    ).resources
    return row
