"""Acceptance: the wave-one detectors together, end to end through the MCP server.

Given the decision "Production platform baseline" (six claims: public access disabled, private endpoint present,
managed identity, owner tag, region, storage SKU) and the sample estate; when drift_evaluate runs; then the verdicts
equal tests/acceptance/golden/wave-one.verdicts.json (keyed by detector, then resource name), there is one review
proposal per contradicted claim, and the score is the severity-weighted share of supported findings.

The scenario runs in-process and over streamable HTTP, which also proves that a valued expectation (`exists` with no
value, `in` with a list) crosses the wire unchanged.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from cloud_crawler_core.ledger import InMemoryLedger
from mcp.client import Client

from cloud_crawler_appliance.mcp_server import build_mcp_server

GOLDEN = Path(__file__).with_name("golden") / "wave-one.verdicts.json"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
ACTOR = "00000000-0000-0000-0000-000000000011"  # a placeholder object id; never a real one


async def scenario(client: Client, wave_one_decision: dict, sample_export: dict) -> dict:
    created = await client.call_tool("adr_create", {"decision": wave_one_decision})
    assert created.is_error is False, created.content
    decision_id = created.structured_content["decisionId"]
    assert len(created.structured_content["claimIds"]) == 6
    accepted = await client.call_tool("adr_accept", {"decisionId": decision_id, "actorId": ACTOR})
    assert accepted.is_error is False, accepted.content

    ingested = await client.call_tool(
        "evidence_ingest",
        {
            "kind": "arg-export",
            "evidenceClass": "imported",
            "payload": sample_export,
            "subject": {"scope": "subscription", "subscriptionId": SUBSCRIPTION},
            "provenance": {"sourceType": "upload", "artifactName": "sample-resource-graph.json"},
        },
    )
    assert ingested.is_error is False, ingested.content
    assert ingested.structured_content["resourceCount"] == 13

    evaluated = await client.call_tool("drift_evaluate", {"decisionId": decision_id})
    assert evaluated.is_error is False, evaluated.content
    result = evaluated.structured_content["result"]
    detectors = {f["detectorId"] for f in result["findings"]}
    verdicts: dict[str, dict[str, str]] = {d: {} for d in sorted(detectors)}
    for finding in result["findings"]:
        verdicts[finding["detectorId"]][finding["resourceId"].rsplit("/", 1)[-1]] = finding["verdict"]
    assert verdicts == json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert result["summary"] == {
        "supported": 32,
        "contradicted": 7,
        "unknown": 0,
        "notApplicable": 39,
        "score": 77.0,
        "coverage": 1.0,
    }
    assert len(result["contradictions"]) == 7
    assert len(result["proposals"]) == 5 and all(p["kind"] == "contradiction" for p in result["proposals"])
    app = [f for f in result["findings"] if f["resourceId"].endswith("/hcw-sample-app-prod-01")]
    assert {f["detectorId"]: f["verdict"] for f in app} == {
        "public-access-disabled": "contradicted",
        "private-endpoint-present": "not-applicable",
        "managed-identity": "contradicted",
        "tag-required": "contradicted",
        "region-allowed": "contradicted",
        "sku-allowed": "not-applicable",
    }
    owner = next(f for f in app if f["detectorId"] == "tag-required")
    assert owner["observed"] == {"tag": None, "reading": None} and owner["expected"] == {"tag": None}
    region = next(f for f in app if f["detectorId"] == "region-allowed")
    assert region["observed"] == {"location": "eastus2", "reading": "eastus2"}
    assert region["expected"] == {"location": ["centralus"]}

    # the lab page's views: evidence without payloads, findings by verdict, open contradictions and proposals
    listed = await client.call_tool("evidence_list", {})
    assert listed.structured_content["total"] == 1
    [summary] = listed.structured_content["evidence"]
    assert summary["resourceCount"] == 13 and "payload" not in summary and summary["sourceType"] == "upload"
    drift = await client.call_tool("drift_list", {"decisionId": decision_id, "verdict": "contradicted"})
    assert drift.structured_content["total"] == 7
    open_contradictions = await client.call_tool("contradiction_list", {"decisionId": decision_id})
    assert open_contradictions.structured_content["total"] == 7
    reviews = await client.call_tool("review_list", {"decisionId": decision_id})
    assert reviews.structured_content["total"] == 5

    # a person decides one proposal; the model's tool list never carries review_decide (the site enforces that)
    proposal_id = reviews.structured_content["proposals"][0]["proposalId"]
    decided = await client.call_tool(
        "review_decide",
        {"proposalId": proposal_id, "decision": "approve", "actorId": ACTOR, "comment": "fix in the next sprint"},
    )
    assert decided.is_error is False, decided.content
    assert decided.structured_content["status"] == "approved"
    assert decided.structured_content["approval"]["actorId"].startswith("sha256:")
    assert decided.structured_content["approval"]["evidenceSnapshotHash"].startswith("sha256:")
    assert ACTOR not in str(decided.content)
    remaining = await client.call_tool("review_list", {"decisionId": decision_id})
    assert remaining.structured_content["total"] == 4
    again = await client.call_tool("review_decide", {"proposalId": proposal_id, "decision": "reject", "actorId": ACTOR})
    assert again.is_error is True  # decided once
    return result


def test_in_process(wave_one_decision, sample_export, quiet_env):
    from cloud_crawler_appliance.security import logging as logs

    logs.configure(silent=True)
    server = build_mcp_server(InMemoryLedger())

    async def run():
        async with Client(server) as client:
            return await scenario(client, wave_one_decision, sample_export)

    asyncio.run(run())


def test_over_streamable_http(http_server, wave_one_decision, sample_export):
    async def run():
        async with Client(f"{http_server}/mcp") as client:
            return await scenario(client, wave_one_decision, sample_export)

    asyncio.run(run())
