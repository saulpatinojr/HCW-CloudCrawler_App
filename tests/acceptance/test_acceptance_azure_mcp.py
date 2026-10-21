"""Acceptance: the Azure observation scenarios of the website proposal (section 21) with recorded Azure MCP results.

Retirement review generation: a recorded `advisor_recommendation_list` with one ServiceUpgradeAndRetirement record
dated within 180 days against hcw-sample-redis-01, and a decision claiming no exposure, gives a retirement proposal
naming the resource, the date and the Advisor remediation, status open. Advisor contradiction detection: one `New`
high-impact HighAvailability record in scope is contradicted with one evidence id; the `Dismissed` one appears as
accepted risk, not a contradiction. Policy: the baseline initiative is assigned.

The appliance runs with the recorded host (`CC_AZMCP_MODE=recorded`), so `collection_run_azure` exists and drives the
standard sequence; the same scenario then runs over streamable HTTP.
"""

from __future__ import annotations

import asyncio

from cloud_crawler_core.ledger import InMemoryLedger
from mcp.client import Client

from cloud_crawler_appliance.mcp_host import RecordedAzureMcpHost
from cloud_crawler_appliance.mcp_server import build_mcp_server

SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
ACTOR = "00000000-0000-0000-0000-000000000011"


async def scenario(client: Client, observations_decision: dict) -> None:
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert tools["collection_run_azure"].meta == {**tools["adr_create"].meta, "callsAzure": True, "caller": "human"}
    assert all(t.meta["callsAzure"] is False for name, t in tools.items() if name != "collection_run_azure")

    created = await client.call_tool("adr_create", {"decision": observations_decision})
    assert created.is_error is False, created.content
    decision_id = created.structured_content["decisionId"]

    collected = await client.call_tool("collection_run_azure", {"subscriptionId": SUBSCRIPTION, "actorId": ACTOR})
    assert collected.is_error is False, collected.content
    run = collected.structured_content["run"]
    assert (
        run["summary"] == {"evidence": 5, "rows": 7, "errors": 0}
        and collected.structured_content["azureConnectivity"] == "recorded"
    )
    assert ACTOR not in str(collected.content)
    listed = await client.call_tool("evidence_list", {"kind": "azure-mcp-result"})
    assert listed.structured_content["total"] == 5
    assert all(
        e["sourceType"] == "azure-mcp" and e["collectionRunId"] == run["runId"]
        for e in listed.structured_content["evidence"]
    )

    evaluated = await client.call_tool("drift_evaluate", {"decisionId": decision_id})
    assert evaluated.is_error is False, evaluated.content
    result = evaluated.structured_content["result"]
    by_detector: dict[str, list] = {}
    for finding in result["findings"]:
        by_detector.setdefault(finding["detectorId"], []).append(finding)
    advisor = {f["resourceId"].rsplit("/", 1)[-1]: f for f in by_detector["advisor-findings"]}
    assert (
        advisor["hcw-sample-sql-01"]["verdict"] == "contradicted"
        and len(advisor["hcw-sample-sql-01"]["evidenceIds"]) == 1
    )
    assert advisor["hcw-sample-cosmos-prod-01"]["verdict"] == "supported"
    assert advisor["hcw-sample-cosmos-prod-01"]["observed"]["acceptedRisk"] is True
    [retirement] = by_detector["retirement-exposure"]
    assert retirement["verdict"] == "contradicted" and retirement["resourceId"].endswith("/hcw-sample-redis-01")
    [policy] = by_detector["policy-assignment-present"]
    assert policy["verdict"] == "supported"
    assert result["summary"] == {
        "supported": 2,
        "contradicted": 2,
        "unknown": 0,
        "notApplicable": 0,
        "score": 45.5,
        "coverage": 1.0,
    }

    proposals = {p["kind"]: p for p in result["proposals"]}
    assert set(proposals) == {"contradiction", "retirement"}
    retirement_proposal = proposals["retirement"]
    assert retirement_proposal["status"] == "open" and "2027-03-31" in retirement_proposal["title"]
    assert retirement_proposal["impactedResourceIds"] == [retirement["resourceId"]]
    assert retirement_proposal["recommendedActions"][0]["source"] == "advisor"
    assert retirement_proposal["dueBy"].startswith("2027-03-31")

    reviews = await client.call_tool("review_list", {"decisionId": decision_id})
    assert reviews.structured_content["total"] == 2
    refused = await client.call_tool(
        "collection_run_azure", {"subscriptionId": "00000000-0000-0000-0000-000000000009", "actorId": ACTOR}
    )
    assert refused.is_error is False  # the run completes; failures are recorded per source, never hidden
    assert refused.structured_content["run"]["errors"] == ["no_recording"] * 4


def test_in_process(observations_decision, recordings_dir, quiet_env):
    from cloud_crawler_appliance.security import logging as logs

    logs.configure(silent=True)
    server = build_mcp_server(InMemoryLedger(), host=RecordedAzureMcpHost.from_directory(recordings_dir))

    async def run():
        async with Client(server) as client:
            await scenario(client, observations_decision)

    asyncio.run(run())


def test_over_streamable_http(recorded_http_server, observations_decision):
    async def run():
        async with Client(f"{recorded_http_server}/mcp") as client:
            await scenario(client, observations_decision)

    asyncio.run(run())


def test_without_a_host_the_tool_does_not_exist(quiet_env):
    from cloud_crawler_appliance.security import logging as logs

    logs.configure(silent=True)

    async def run():
        async with Client(build_mcp_server(InMemoryLedger())) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert "collection_run_azure" not in names

    asyncio.run(run())
