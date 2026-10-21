"""The valued governance detectors of wave one: `tag-required`, `sku-allowed`, `region-allowed`. Each reads one value
from any resource and the claim's expectation compares it (`exists`, `in`, `eq`, `neq`, ...; `base.compare`).

- `tag-required` takes the parameter `tag` (the tag name, matched case-insensitively as Azure does) and reads its
  value, `None` when the tag is missing. `exists` claims the tag is present; `in [...]` claims its value is one of
  the allowed ones.
- `sku-allowed` reads `sku.name` (or `sku.tier` with the parameter `field: tier`); a resource without a SKU answers
  unknown, because the export cannot say which SKU a SKU-less type runs.
- `region-allowed` reads `location`; `in [...]` claims the region is allowed. `global` resources carry `global`.
"""

from __future__ import annotations

from typing import Any

from cloud_crawler_core.detectors.base import ANY_TYPE, Detector, Reading, tag_of
from cloud_crawler_core.models import NormalizedResource


def tag_value(resource: NormalizedResource, parameters: dict[str, Any]) -> Reading:
    name = parameters.get("tag")
    if not isinstance(name, str) or not name:
        return Reading(None, None, "the claim parameter tag (the tag name) is required")
    return Reading(True, tag_of(resource, name))


TAG_REQUIRED = Detector(
    detector_id="tag-required",
    version="1.0.0",
    question="What is the value of the required tag?",
    readers={ANY_TYPE: tag_value},
    valued=True,
)


def sku_value(resource: NormalizedResource, parameters: dict[str, Any]) -> Reading:
    field = parameters.get("field", "name")
    if field not in ("name", "tier"):
        return Reading(None, None, "the claim parameter field must be name or tier")
    value = resource.sku.get(field)
    if not isinstance(value, str) or not value:
        return Reading(None, value, f"sku.{field} is absent")
    return Reading(True, value)


SKU_ALLOWED = Detector(
    detector_id="sku-allowed",
    version="1.0.0",
    question="Which SKU does the resource run?",
    readers={ANY_TYPE: sku_value},
    valued=True,
)


def region_value(resource: NormalizedResource, _: dict[str, Any]) -> Reading:
    if not resource.location:
        return Reading(None, None, "location is absent")
    return Reading(True, resource.location)


REGION_ALLOWED = Detector(
    detector_id="region-allowed",
    version="1.0.0",
    question="Which region is the resource in?",
    readers={ANY_TYPE: region_value},
    valued=True,
)
