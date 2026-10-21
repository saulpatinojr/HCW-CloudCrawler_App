"""The standard collection sequence (website proposal, section 10.2): `subscription_list` -> `group_list` ->
`advisor_recommendation_list` (open high-impact reliability findings, then service retirements within 180 days) ->
`policy_assignment_list`, each result ingested as observed evidence under one collection run. A tool that fails
is recorded in the run as an error code and the sequence continues; nothing is retried, nothing is written to
Azure."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cloud_crawler_core.ids import new_id
from cloud_crawler_core.ledger import InMemoryLedger
from cloud_crawler_core.models import CollectionRun, RunSource, ScopeKind, SourceType, Subject

from cloud_crawler_appliance.mcp_host.host import AzureMcpHost, HostError, evidence_from_result

RETIREMENT_WINDOW_DAYS = 180


def standard_sequence(subscription_id: str, now: datetime) -> list[tuple[str, dict]]:
    horizon = (now.astimezone(UTC) + timedelta(days=RETIREMENT_WINDOW_DAYS)).date().isoformat()
    return [
        ("subscription_list", {}),
        ("group_list", {"subscription": subscription_id}),
        (
            "advisor_recommendation_list",
            {"subscription": subscription_id, "category": "HighAvailability", "impact": "High", "status": "New"},
        ),
        (
            "advisor_recommendation_list",
            {
                "subscription": subscription_id,
                "sub-category": "ServiceUpgradeAndRetirement",
                "retirement-date": f"le:{horizon}",
            },
        ),
        ("policy_assignment_list", {"subscription": subscription_id}),
    ]


async def collect(
    host: AzureMcpHost,
    ledger: InMemoryLedger,
    *,
    subscription_id: str,
    trigger: str = "operator",
    actor_hash: str | None = None,
    max_rows: int = 5_000,
    now: datetime | None = None,
) -> CollectionRun:
    started = now or datetime.now(UTC)
    run_id = new_id("run")
    sources: list[RunSource] = []
    errors: list[str] = []
    evidence_count = 0
    row_count = 0
    for tool, arguments in standard_sequence(subscription_id, started):
        try:
            result = await host.call(tool, arguments)
            record = evidence_from_result(
                result,
                identity_mode=host.identity_mode,
                now=started,
                collection_run_id=run_id,
                max_rows=max_rows,
                actor_hash=actor_hash,
            )
        except HostError as exc:
            errors.append(exc.code)
            sources.append(RunSource(sourceType=SourceType.AZURE_MCP, tool=tool, status=exc.code))
            continue
        ledger.add_evidence(record)
        rows = len(record.payload.get("rows", [])) if isinstance(record.payload, dict) else 0
        evidence_count += 1
        row_count += rows
        sources.append(
            RunSource(sourceType=SourceType.AZURE_MCP, tool=tool, itemCount=rows, evidenceIds=[record.evidenceId])
        )
    return CollectionRun(
        runId=run_id,
        startedAt=started,
        finishedAt=datetime.now(UTC) if now is None else started,
        trigger=trigger,
        identityMode=host.identity_mode,
        scope=Subject(scope=ScopeKind.SUBSCRIPTION, subscriptionId=subscription_id.lower()),
        sources=sources,
        errors=errors,
        summary={"evidence": evidence_count, "rows": row_count, "errors": len(errors)},
    )
