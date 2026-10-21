"""Azure Resource Graph JSON export -> NormalizedResource rows.

Accepted shapes: the portal's export (`{"count": n, "data": [...]}`), the CLI's (`{"data": [...]}`), or a bare array.
Each row needs `id`, `type` and `name`; everything else is optional. Types and ids are case-folded because Resource
Graph itself is case-insensitive about them and exports mix cases. Nothing is inferred here: derivations such as
"is this zone redundant" belong to the detector that owns the question.
"""

from __future__ import annotations

from typing import Any

from cloud_crawler_core.models import NormalizedResource

DEFAULT_MAX_ROWS = 5_000


class IngestionError(ValueError):
    """A payload that is not a Resource Graph export, or that exceeds the row limit. The message is content-free."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    raise IngestionError("invalid_request", "a Resource Graph export is a JSON array or an object with a data array")


def _str_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): ("" if v is None else str(v)) for k, v in value.items()}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _zones(value: Any) -> list[str]:
    if isinstance(value, list):
        return sorted(str(z) for z in value)
    return []


def _segment(resource_id: str, marker: str) -> str | None:
    parts = resource_id.split("/")
    lowered = [p.lower() for p in parts]
    try:
        index = lowered.index(marker.lower())
    except ValueError:
        return None
    return parts[index + 1] if index + 1 < len(parts) else None


def parse_resource_graph_json(payload: Any, *, max_rows: int = DEFAULT_MAX_ROWS) -> list[NormalizedResource]:
    rows = _rows(payload)
    if len(rows) > max_rows:
        raise IngestionError("too_many_rows", f"export has more than {max_rows} rows")
    resources: list[NormalizedResource] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise IngestionError("invalid_request", f"row {index} is not an object")
        resource_id = row.get("id")
        resource_type = row.get("type")
        name = row.get("name")
        if not (isinstance(resource_id, str) and isinstance(resource_type, str) and isinstance(name, str)):
            raise IngestionError("invalid_request", f"row {index} lacks id, type or name")
        rid = resource_id.lower()
        resources.append(
            NormalizedResource(
                id=rid,
                type=resource_type.lower(),
                name=name,
                location=str(row["location"]).lower() if isinstance(row.get("location"), str) else None,
                resourceGroup=(
                    str(row["resourceGroup"])
                    if isinstance(row.get("resourceGroup"), str)
                    else _segment(resource_id, "resourceGroups")
                ),
                subscriptionId=(
                    str(row["subscriptionId"]).lower()
                    if isinstance(row.get("subscriptionId"), str)
                    else (_segment(resource_id, "subscriptions") or "").lower() or None
                ),
                zones=_zones(row.get("zones")),
                sku=_dict(row.get("sku")),
                identity=_dict(row.get("identity")),
                tags=_str_dict(row.get("tags")),
                properties=_dict(row.get("properties")),
            )
        )
    return resources
