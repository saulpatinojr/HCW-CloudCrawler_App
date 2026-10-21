"""The MCP tool catalogue in-process: caller classes, listing filters, human-class validation, error codes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from cloud_crawler_core.ledger import InMemoryLedger
from mcp.client import Client

from cloud_crawler_appliance.mcp_server import MAX_LIMIT, build_mcp_server
from cloud_crawler_appliance.security import logging as logs

ACTOR = "00000000-0000-0000-0000-000000000012"
OTHER_ACTOR = "00000000-0000-0000-0000-000000000013"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"


class Session:
    """`await call(tool, **args)` over one in-process client: structured content, or `{"error": text}`."""

    def __init__(self, client: Client, ledger: InMemoryLedger, decision: dict) -> None:
        self.client = client
        self.ledger = ledger
        self.decision = decision
        self.decision_id = ""

    async def __call__(self, tool: str, **args: Any) -> Any:
        result = await self.client.call_tool(tool, args)
        if result.is_error:
            return {"error": "".join(getattr(c, "text", "") for c in result.content)}
        return result.structured_content


Body = Callable[[Session], Coroutine[Any, Any, Any]]


@pytest.fixture
def run(sample_export, wave_one_decision) -> Callable[[Body], Any]:
    """Run `body(call)` with the wave-one decision and the sample evidence in the ledger (nothing evaluated)."""
    logs.configure(silent=True)

    def _run(body: Body) -> Any:
        async def main() -> Any:
            ledger = InMemoryLedger()
            async with Client(build_mcp_server(ledger)) as client:
                call = Session(client, ledger, wave_one_decision)
                created = await call("adr_create", decision=wave_one_decision)
                await call(
                    "evidence_ingest",
                    kind="arg-export",
                    evidenceClass="imported",
                    payload=sample_export,
                    subject={"scope": "subscription", "subscriptionId": SUBSCRIPTION},
                    provenance={"sourceType": "upload"},
                )
                call.decision_id = created["decisionId"]
                return await body(call)

        return asyncio.run(main())

    return _run


def test_every_tool_declares_caller_class_and_no_azure(run):
    async def body(call: Session):
        tools = (await call.client.list_tools()).tools
        by_name = {t.name: t for t in tools}
        assert set(by_name) == {
            "adr_create",
            "adr_accept",
            "adr_get",
            "adr_list",
            "evidence_ingest",
            "evidence_list",
            "evidence_get",
            "drift_evaluate",
            "drift_list",
            "contradiction_list",
            "review_list",
            "review_get",
            "review_decide",
        }
        assert all(t.meta["callsAzure"] is False and t.meta["caller"] in ("model", "human") for t in tools)
        assert {n for n, t in by_name.items() if t.meta["caller"] == "human"} == {"adr_accept", "review_decide"}
        read_only = {n for n, t in by_name.items() if t.annotations.read_only_hint}
        assert read_only == {
            "adr_get",
            "adr_list",
            "evidence_list",
            "evidence_get",
            "drift_list",
            "contradiction_list",
            "review_list",
            "review_get",
        }
        assert all(t.annotations.destructive_hint is False and t.annotations.open_world_hint is False for t in tools)
        # the model may not create an accepted decision: the input schema only allows draft or proposed
        status_schema = by_name["adr_create"].input_schema["$defs"]["DecisionInput"]["properties"]["status"]
        assert set(status_schema["enum"]) == {"draft", "proposed"}

    run(body)


def test_adr_create_rejects_accepted_status(run):
    async def body(call: Session):
        assert "error" in await call("adr_create", decision={**call.decision, "status": "accepted"})
        proposed = await call("adr_create", decision={**call.decision, "status": "proposed"})
        assert proposed["status"] == "proposed"

    run(body)


def test_adr_accept_is_a_hashed_human_act(run):
    async def body(call: Session):
        first = await call("adr_accept", decisionId=call.decision_id, actorId=ACTOR, comment="agreed in review")
        assert first["status"] == "accepted" and first["version"] == 2
        assert first["acceptedBy"].startswith("sha256:") and ACTOR not in json.dumps(first)
        again = await call("adr_accept", decisionId=call.decision_id, actorId=OTHER_ACTOR)
        assert again == first  # idempotent: the first acceptance stands
        blank = await call("adr_accept", decisionId=call.decision_id, actorId="  ")
        assert "actorId is required" in blank["error"]
        missing = await call("adr_accept", decisionId="dec_missing", actorId=ACTOR)
        assert "not_found" in missing["error"]
        record = await call("adr_get", decisionId=call.decision_id)
        assert record["status"] == "accepted" and record["acceptedBy"] == first["acceptedBy"]
        assert "not_found" in (await call("adr_get", decisionId="dec_missing"))["error"]

    run(body)


def test_adr_list_filters_and_pages(run):
    async def body(call: Session):
        for _ in range(3):
            await call("adr_create", decision=call.decision)
        assert (await call("adr_list"))["total"] == 4
        assert len((await call("adr_list", limit=2))["decisions"]) == 2
        assert (await call("adr_list", status="accepted"))["total"] == 0
        await call("adr_accept", decisionId=call.decision_id, actorId=ACTOR)
        listed = await call("adr_list", status="accepted")
        assert listed["total"] == 1 and listed["decisions"][0]["claimCount"] == 6
        assert len((await call("adr_list", limit=10_000))["decisions"]) == 4 and MAX_LIMIT == 200

    run(body)


def test_evidence_list_and_get_carry_no_raw_payload(run):
    async def body(call: Session):
        listed = await call("evidence_list")
        assert listed["total"] == 1
        [summary] = listed["evidence"]
        assert set(summary) >= {"evidenceId", "payloadHash", "resourceCount", "confidence", "expiresAt"}
        assert "payload" not in summary and summary["subscriptionId"] == SUBSCRIPTION
        assert (await call("evidence_list", kind="azqr-report"))["total"] == 0
        assert (await call("evidence_list", evidenceClass="imported"))["total"] == 1
        record = (await call("evidence_get", evidenceId=summary["evidenceId"]))["evidence"]
        assert record["payload"].keys() == {"resources"} and record["class"] == "imported"
        assert "not_found" in (await call("evidence_get", evidenceId="ev_missing"))["error"]

    run(body)


def test_drift_list_contradictions_and_reviews(run):
    async def body(call: Session):
        decision_id = call.decision_id
        assert (await call("drift_list", decisionId=decision_id))["total"] == 0  # nothing evaluated yet
        evaluated = (await call("drift_evaluate", decisionId=decision_id))["result"]
        assert (await call("drift_list", decisionId=decision_id))["total"] == len(evaluated["findings"]) == 78
        assert (await call("drift_list", decisionId=decision_id, verdict="unknown"))["total"] == 0
        page = await call("drift_list", decisionId=decision_id, verdict="contradicted", limit=3)
        assert page["total"] == 7 and len(page["findings"]) == 3
        assert "not_found" in (await call("drift_list", decisionId="dec_missing"))["error"]
        assert (await call("contradiction_list"))["total"] == 7
        assert (await call("contradiction_list", decisionId=decision_id))["total"] == 7
        assert "not_found" in (await call("contradiction_list", decisionId="dec_missing"))["error"]
        # re-evaluation keeps the same open contradictions (merged by claim and resource), not twice as many
        await call("drift_evaluate", decisionId=decision_id)
        assert (await call("contradiction_list"))["total"] == 7
        reviews = await call("review_list", decisionId=decision_id)
        assert reviews["total"] == 10  # one proposal per contradicted claim per evaluation; deciding closes them
        assert (await call("review_list", status="approved"))["total"] == 0
        assert "not_found" in (await call("review_list", decisionId="dec_missing"))["error"]
        proposal_id = reviews["proposals"][0]["proposalId"]
        got = await call("review_get", proposalId=proposal_id)
        assert got["proposal"]["kind"] == "contradiction" and got["approvals"] == []
        assert "not_found" in (await call("review_get", proposalId="prp_missing"))["error"]

    run(body)


def test_review_decide_records_a_hashed_approval_once(run):
    async def body(call: Session):
        await call("drift_evaluate", decisionId=call.decision_id)
        proposal_id = (await call("review_list"))["proposals"][0]["proposalId"]
        blank = await call("review_decide", proposalId=proposal_id, decision="approve", actorId="")
        assert "actorId is required" in blank["error"]
        rejected = await call(
            "review_decide", proposalId=proposal_id, decision="reject", actorId=ACTOR, actorRole="lead"
        )
        assert rejected["status"] == "rejected"
        approval = rejected["approval"]
        assert approval["decision"] == "reject" and approval["actorRole"] == "lead"
        assert approval["actorId"].startswith("sha256:") and ACTOR not in json.dumps(rejected)
        assert approval["evidenceSnapshotHash"].startswith("sha256:")
        assert (await call("review_get", proposalId=proposal_id))["approvals"] == [approval]
        twice = await call("review_decide", proposalId=proposal_id, decision="approve", actorId=ACTOR)
        assert "invalid_state" in twice["error"]
        missing = await call("review_decide", proposalId="prp_missing", decision="approve", actorId=ACTOR)
        assert "not_found" in missing["error"]
        assert (await call("review_list", status="rejected"))["total"] == 1
        everything = await call("review_list", status=None)
        assert everything["total"] == (await call("review_list"))["total"] + 1

    run(body)
