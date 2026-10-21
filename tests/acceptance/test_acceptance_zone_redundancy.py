"""Acceptance: the zone-redundancy contradiction, end to end through the MCP server (website proposal, section 21).

Given decision D-0001 claims zone redundancy for env=prod data-platform resources, and an uploaded export shows
hcw-sample-sql-01 with zoneRedundant=false; when drift_evaluate runs; then one contradicted finding exists for that
resource (and one for the Cosmos DB account with a non-zone-redundant location), one contradiction record and one
review proposal of kind contradiction, and the score is unaffected by an unknown sibling.

Runs twice: in-process against the MCP server object, and over streamable HTTP against the mounted FastAPI app, with
the golden verdicts in tests/acceptance/golden/zone-redundancy.verdicts.json.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from cloud_crawler_core.ledger import InMemoryLedger
from mcp.client import Client

from cloud_crawler_appliance.api import create_app
from cloud_crawler_appliance.config import Settings
from cloud_crawler_appliance.mcp_server import build_mcp_server

GOLDEN = Path(__file__).with_name("golden") / "zone-redundancy.verdicts.json"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"


async def scenario(client: Client, sample_decision: dict, sample_export: dict) -> dict:
    tools = await client.list_tools()
    names = {t.name for t in tools.tools}
    assert {"adr_create", "evidence_ingest", "drift_evaluate"} <= names
    assert all((t.meta or {}).get("callsAzure") is False for t in tools.tools)
    assert client.server_info is not None and client.server_info.name == "cloud-crawler"

    created = await client.call_tool("adr_create", {"decision": sample_decision})
    assert created.is_error is False, created.content
    decision_id = created.structured_content["decisionId"]
    assert len(created.structured_content["claimIds"]) == 1

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
    assert ingested.structured_content["resourceCount"] == sample_export["count"]
    assert ingested.structured_content["confidence"] == 0.74  # unauthenticated upload
    assert ingested.structured_content["payloadHash"].startswith("sha256:")

    evaluated = await client.call_tool("drift_evaluate", {"decisionId": decision_id})
    assert evaluated.is_error is False, evaluated.content
    result = evaluated.structured_content["result"]
    verdicts = {f["resourceId"].rsplit("/", 1)[-1]: f["verdict"] for f in result["findings"]}
    assert verdicts == json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert result["summary"] == {
        "supported": 3,
        "contradicted": 2,
        "unknown": 0,
        "notApplicable": 6,
        "score": 60.0,
        "coverage": 1.0,
    }
    assert len(result["contradictions"]) == 2
    [proposal] = result["proposals"]
    assert proposal["kind"] == "contradiction" and proposal["status"] == "open"
    sql = next(f for f in result["findings"] if f["resourceId"].endswith("/hcw-sample-sql-01"))
    assert sql["verdict"] == "contradicted" and sql["observed"] == {"zoneRedundant": False, "reading": False}
    assert sql["expected"] == {"zoneRedundant": True} and sql["evidenceIds"] == [
        ingested.structured_content["evidenceId"]
    ]

    missing = await client.call_tool("drift_evaluate", {"decisionId": "dec_missing"})
    assert missing.is_error is True
    bad = await client.call_tool(
        "evidence_ingest",
        {
            "kind": "arg-export",
            "evidenceClass": "imported",
            "payload": {"data": "not rows"},
            "subject": {"scope": "subscription"},
            "provenance": {"sourceType": "upload"},
        },
    )
    assert bad.is_error is True
    return result


def test_in_process(sample_decision, sample_export, quiet_env):
    from cloud_crawler_appliance.security import logging as logs

    logs.configure(silent=True)
    server = build_mcp_server(InMemoryLedger())

    async def run():
        async with Client(server) as client:
            return await scenario(client, sample_decision, sample_export)

    asyncio.run(run())


@pytest.fixture
def http_server(quiet_env):
    app = create_app(Settings.from_env(quiet_env), env=quiet_env)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_over_streamable_http(http_server, sample_decision, sample_export):
    async def run():
        async with Client(f"{http_server}/mcp") as client:
            assert client.protocol_version == "2026-07-28"
            return await scenario(client, sample_decision, sample_export)

    asyncio.run(run())
