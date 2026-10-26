"""Acceptance: Terraform state and plan evidence, end to end through the MCP server (ticket #54).

Given the sample estate as a Terraform state and as a plan, and the decisions of the other acceptance tests; when
drift_evaluate runs; then the verdicts equal the golden files in tests/acceptance/golden, which equal the verdicts of
the Resource Graph export of the same estate (wave-one.verdicts.json, zone-redundancy.verdicts.json) for every claim
whose properties Terraform carries, and are `unknown` with a reason, never a different answer, for the rest. The four
that differ are the private endpoint claims: a private endpoint is a resource of its own, not an attribute of the
resource it protects.

Runs in-process and over streamable HTTP. Regenerate the Terraform goldens with CC_UPDATE_SNAPSHOT=1, locally, and
read the diff against the Resource Graph ones before committing.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from cloud_crawler_core.ledger import InMemoryLedger
from mcp.client import Client

from cloud_crawler_appliance.mcp_server import build_mcp_server

GOLDEN = Path(__file__).with_name("golden")
SAMPLES = Path(__file__).resolve().parents[2] / "samples"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
ACTOR = "00000000-0000-0000-0000-000000000011"  # a placeholder object id; never a real one
SECRETS = ("fictional-placeholder", "fictional-private-blob", "sensitive_attributes")

# The claims Terraform cannot answer for the sample estate: what protects a resource with a private endpoint is a
# separate azurerm_private_endpoint resource, so the resource's own attributes say nothing about it.
CANNOT_ANSWER = {
    ("private-endpoint-present", "hcw-sample-cosmos-prod-01"),
    ("private-endpoint-present", "hcw-sample-kv-prod-01"),
    ("private-endpoint-present", "hcw-sample-sqlsrv-01"),
    ("private-endpoint-present", "hcwsamplestprod01"),
}


def document(name: str) -> dict:
    return json.loads((SAMPLES / "terraform" / name).read_text(encoding="utf-8"))


def golden(name: str, current: Any) -> Any:
    path = GOLDEN / name
    if os.environ.get("CC_UPDATE_SNAPSHOT") == "1":
        path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8", newline="\n")
    return json.loads(path.read_text(encoding="utf-8"))


async def evaluate(client: Client, decision: dict, kind: str, payload: dict) -> tuple[dict, dict]:
    created = await client.call_tool("adr_create", {"decision": decision})
    assert created.is_error is False, created.content
    decision_id = created.structured_content["decisionId"]
    accepted = await client.call_tool("adr_accept", {"decisionId": decision_id, "actorId": ACTOR})
    assert accepted.is_error is False, accepted.content
    ingested = await client.call_tool(
        "evidence_ingest",
        {
            "kind": kind,
            "evidenceClass": "imported",
            "payload": payload,
            "subject": {"scope": "subscription", "subscriptionId": SUBSCRIPTION},
            "provenance": {"sourceType": "upload", "artifactName": f"sample-estate.{kind}.json"},
        },
    )
    assert ingested.is_error is False, ingested.content
    evaluated = await client.call_tool("drift_evaluate", {"decisionId": decision_id})
    assert evaluated.is_error is False, evaluated.content
    return ingested.structured_content, evaluated.structured_content["result"]


def by_detector(result: dict) -> dict[str, dict[str, str]]:
    verdicts: dict[str, dict[str, str]] = {d: {} for d in sorted({f["detectorId"] for f in result["findings"]})}
    for finding in result["findings"]:
        verdicts[finding["detectorId"]][finding["resourceId"].rsplit("/", 1)[-1]] = finding["verdict"]
    return verdicts


def as_pairs(verdicts: dict[str, dict[str, str]]) -> dict[tuple[str, str], str]:
    return {(d, name): verdict for d, names in verdicts.items() for name, verdict in names.items()}


async def scenario(client: Client, wave_one_decision: dict, sample_decision: dict, kind: str, file: str) -> None:
    payload = document(file)
    plan = kind == "tf-plan"

    # the wave-one decision: six claims over the estate
    ingested, result = await evaluate(client, wave_one_decision, kind, payload)
    assert ingested["kind"] == kind and ingested["evidenceClass"] == "imported"
    assert ingested["resourceCount"] == (15 if plan else 13)
    assert ingested["confidence"] == 0.74  # an unauthenticated upload
    assert ingested["payloadHash"].startswith("sha256:")
    verdicts = by_detector(result)
    expected = golden(f"wave-one.terraform-{'plan' if plan else 'state'}.verdicts.json", verdicts)
    assert verdicts == expected

    # against the same estate as a Resource Graph export: the same answer, or unknown, for every resource it holds
    export = json.loads((GOLDEN / "wave-one.verdicts.json").read_text(encoding="utf-8"))
    arg, tf = as_pairs(export), as_pairs(verdicts)
    assert arg.keys() <= tf.keys()
    different = {pair for pair in arg if tf[pair] != arg[pair]}
    assert different == CANNOT_ANSWER
    assert all(tf[pair] == "unknown" for pair in different)
    reasons = {
        (f["detectorId"], f["resourceId"].rsplit("/", 1)[-1]): f["unknownReason"]
        for f in result["findings"]
        if f["verdict"] == "unknown"
    }
    assert set(reasons) >= CANNOT_ANSWER
    assert all("privateEndpointConnections" in reasons[pair] for pair in CANNOT_ANSWER)

    # what the plan adds: a storage account it creates (an Azure id appears only after apply) and a public address
    # whose tags are only known after apply
    if plan:
        logs, new_ip = "terraform:azurerm_storage_account.logs", "terraform:azurerm_public_ip.new"
        assert tf[("sku-allowed", logs)] == "contradicted"  # LRS where ZRS is required, found before it is built
        assert tf[("tag-required", new_ip)] == "unknown"
        assert reasons[("tag-required", new_ip)] == "the evidence behind this resource does not carry its tags"
        assert not any("kv-legacy" in name for _, name in tf)  # the key vault the plan destroys is not judged
        assert result["summary"]["unknown"] == 6

    # the zone-redundancy decision: identical to the export for the state, and for the plan plus what the plan creates
    _, zones = await evaluate(client, sample_decision, kind, payload)
    zone_verdicts = {k: v for d in by_detector(zones).values() for k, v in d.items()}
    zone_export = json.loads((GOLDEN / "zone-redundancy.verdicts.json").read_text(encoding="utf-8"))
    if plan:
        zone_expected = golden("zone-redundancy.terraform-plan.verdicts.json", zone_verdicts)
        assert {k: zone_verdicts[k] for k in zone_export} == zone_export
        assert zone_verdicts == zone_expected
        assert zone_verdicts["terraform:azurerm_storage_account.logs"] == "contradicted"
    else:
        assert zone_verdicts == zone_export
        assert zones["summary"] == {
            "supported": 3,
            "contradicted": 2,
            "unknown": 0,
            "notApplicable": 8,
            "score": 60.0,
            "coverage": 1.0,
        }

    # what is kept: the rows and a summary, never the document, and nothing Terraform marked sensitive
    listed = await client.call_tool("evidence_list", {"kind": kind})
    assert listed.structured_content["total"] == 2
    summaries = listed.structured_content["evidence"]
    assert all("payload" not in e and e["sourceType"] == "upload" for e in summaries)
    record = await client.call_tool("evidence_get", {"evidenceId": summaries[0]["evidenceId"]})
    stored = record.structured_content["evidence"]
    assert set(stored["payload"]) == {"resources", "terraform"}
    assert stored["payload"]["terraform"]["source"] == kind
    text = json.dumps(stored)
    assert not any(secret in text for secret in SECRETS)

    # a document of the wrong shape is refused with a code and stores nothing more
    refused = await client.call_tool(
        "evidence_ingest",
        {
            "kind": kind,
            "evidenceClass": "imported",
            "payload": {"version": 3, "resources": []}
            if not plan
            else {"format_version": "2.0", "resource_changes": []},
            "subject": {"scope": "subscription", "subscriptionId": SUBSCRIPTION},
            "provenance": {"sourceType": "upload"},
        },
    )
    assert refused.is_error is True and "invalid_request" in str(refused.content)
    assert (await client.call_tool("evidence_list", {"kind": kind})).structured_content["total"] == 2


CASES = [("tf-state", "sample-estate.state.json"), ("tf-plan", "sample-estate.plan.json")]


@pytest.mark.parametrize(("kind", "file"), CASES)
def test_in_process(kind, file, wave_one_decision, sample_decision, quiet_env):
    from cloud_crawler_appliance.security import logging as logs

    logs.configure(silent=True)
    server = build_mcp_server(InMemoryLedger())

    async def run():
        async with Client(server) as client:
            await scenario(client, wave_one_decision, sample_decision, kind, file)

    asyncio.run(run())


@pytest.mark.parametrize(("kind", "file"), CASES)
def test_over_streamable_http(kind, file, http_server, wave_one_decision, sample_decision):
    async def run():
        async with Client(f"{http_server}/mcp") as client:
            await scenario(client, wave_one_decision, sample_decision, kind, file)

    asyncio.run(run())
