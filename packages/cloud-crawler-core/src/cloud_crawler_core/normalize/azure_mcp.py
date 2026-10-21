"""Azure MCP Server 3.0.0 `structuredContent` -> observation rows, one normaliser per tool the design calls.

The shapes are the server's result records on the `release/azure/3.x` branch (retrieved 2026-10-21): the Advisor
`RecommendationListResult {recommendations, areResultsTruncated}` whose rows are `Recommendation {id, name, type,
properties}` with camelCase `RecommendationProperties` (the metadata join adds `extendedProperties.retirementDate`,
`retirementFeatureName` and `recommendationSubCategory`); the Policy `PolicyAssignmentListCommandResult
{assignments}`; `SubscriptionListCommandResult {subscriptions}`; the Group `Result {groups}`. Camel-case names come
from the servers' `JsonSerializerContext` naming policy. A payload that lacks the tool's root key is not an error:
the record is stored redacted and unparsed, and no detector reads it.
"""

from __future__ import annotations

from typing import Any

from cloud_crawler_core.models import AdvisorRecommendationRow, PolicyAssignmentRow, ResourceGroupRow, SubscriptionRow
from cloud_crawler_core.normalize.resource_graph import IngestionError, _segment

SUBSCRIPTION_LIST = "subscription_list"
GROUP_LIST = "group_list"
ADVISOR_RECOMMENDATION_LIST = "advisor_recommendation_list"
POLICY_ASSIGNMENT_LIST = "policy_assignment_list"

ROOT_KEYS: dict[str, str] = {
    SUBSCRIPTION_LIST: "subscriptions",
    GROUP_LIST: "groups",
    ADVISOR_RECOMMENDATION_LIST: "recommendations",
    POLICY_ASSIGNMENT_LIST: "assignments",
}


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _lower(value: Any) -> str | None:
    text = _str(value)
    return text.lower() if text else None


def _subscription_of(resource_id: str | None) -> str | None:
    return (_segment(resource_id, "subscriptions") or "").lower() or None if resource_id else None


def _group_of(resource_id: str | None) -> str | None:
    return _segment(resource_id, "resourceGroups") if resource_id else None


def rows_of(tool: str, payload: Any) -> list[Any] | None:
    """The tool's rows, or None when the payload does not carry the tool's root key (stored unparsed)."""
    key = ROOT_KEYS.get(tool)
    if key is None or not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        return None
    return payload[key]


def parse_subscriptions(rows: list[Any]) -> list[SubscriptionRow]:
    out = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not _str(row.get("subscriptionId")):
            raise IngestionError("invalid_request", f"subscription row {index} lacks subscriptionId")
        out.append(
            SubscriptionRow(
                subscriptionId=row["subscriptionId"].lower(),
                displayName=_str(row.get("displayName")),
                state=_str(row.get("state")),
                tenantId=_lower(row.get("tenantId")),
            )
        )
    return out


def parse_groups(rows: list[Any]) -> list[ResourceGroupRow]:
    out = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not _str(row.get("id")) or not _str(row.get("name")):
            raise IngestionError("invalid_request", f"resource group row {index} lacks id or name")
        out.append(
            ResourceGroupRow(
                id=row["id"].lower(),
                name=row["name"],
                location=_lower(row.get("location")),
                subscriptionId=_subscription_of(row["id"]),
            )
        )
    return out


def parse_advisor_recommendations(rows: list[Any]) -> list[AdvisorRecommendationRow]:
    out = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not _str(row.get("id")):
            raise IngestionError("invalid_request", f"recommendation row {index} lacks id")
        properties = row.get("properties") if isinstance(row.get("properties"), dict) else {}
        extended = (
            properties.get("extendedProperties") if isinstance(properties.get("extendedProperties"), dict) else {}
        )
        short = properties.get("shortDescription") if isinstance(properties.get("shortDescription"), dict) else {}
        metadata = properties.get("resourceMetadata") if isinstance(properties.get("resourceMetadata"), dict) else {}
        resource_id = _lower(metadata.get("resourceId"))
        out.append(
            AdvisorRecommendationRow(
                id=row["id"].lower(),
                resourceId=resource_id,
                subscriptionId=_subscription_of(resource_id) or _subscription_of(row["id"]),
                resourceGroup=_group_of(resource_id),
                impactedField=_lower(properties.get("impactedField")),
                impactedValue=_str(properties.get("impactedValue")),
                category=_str(properties.get("category")),
                impact=_str(properties.get("impact")),
                status=_str(properties.get("recommendationStatus")),
                recommendationTypeId=_lower(properties.get("recommendationTypeId")),
                subCategory=_str(extended.get("recommendationSubCategory")),
                retirementDate=_str(extended.get("retirementDate")),
                retirementFeatureName=_str(extended.get("retirementFeatureName")),
                problem=_str(short.get("problem")),
                solution=_str(short.get("solution")),
                dismissReason=_str(properties.get("recommendationDismissReason")),
                lastUpdated=_str(properties.get("lastUpdated")),
            )
        )
    return out


def parse_policy_assignments(rows: list[Any]) -> list[PolicyAssignmentRow]:
    out = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not _str(row.get("id")):
            raise IngestionError("invalid_request", f"policy assignment row {index} lacks id")
        scope = _lower(row.get("scope"))
        out.append(
            PolicyAssignmentRow(
                id=row["id"].lower(),
                name=_str(row.get("name")),
                displayName=_str(row.get("displayName")),
                policyDefinitionId=_lower(row.get("policyDefinitionId")),
                scope=scope,
                subscriptionId=_subscription_of(scope) or _subscription_of(row["id"]),
                enforcementMode=_str(row.get("enforcementMode")),
            )
        )
    return out


PARSERS = {
    SUBSCRIPTION_LIST: parse_subscriptions,
    GROUP_LIST: parse_groups,
    ADVISOR_RECOMMENDATION_LIST: parse_advisor_recommendations,
    POLICY_ASSIGNMENT_LIST: parse_policy_assignments,
}


def parse_azure_mcp_result(tool: str | None, payload: Any, *, max_rows: int) -> dict[str, Any] | None:
    """`{"tool", "rows", "truncated"}` with typed rows, or None when the tool or shape is not one this version
    normalises (the record is then stored unparsed)."""
    if tool is None:
        return None
    rows = rows_of(tool, payload)
    if rows is None:
        return None
    if len(rows) > max_rows:
        raise IngestionError("too_many_rows", f"result has more than {max_rows} rows")
    parsed = PARSERS[tool](rows)
    truncated = bool(payload.get("areResultsTruncated")) if isinstance(payload, dict) else False
    return {"tool": tool, "rows": [r.model_dump(mode="json") for r in parsed], "truncated": truncated}
