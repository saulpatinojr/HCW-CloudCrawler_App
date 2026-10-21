"""The Azure MCP host: the allow-list, the recorded host, the result-to-evidence mapping, the collection sequence,
and the settings that turn the host on."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cloud_crawler_core.ledger import InMemoryLedger
from cloud_crawler_core.models import IdentityMode

from cloud_crawler_appliance.config import Settings
from cloud_crawler_appliance.edition import azure_connectivity
from cloud_crawler_appliance.mcp_host import (
    ALLOWED_TOOLS,
    HostError,
    RecordedAzureMcpHost,
    ToolResult,
    collect,
    evidence_from_result,
    server_params,
)
from cloud_crawler_appliance.mcp_host.collect import standard_sequence
from cloud_crawler_appliance.mcp_host.host import Recording

ROOT = Path(__file__).resolve().parents[2]
RECORDINGS = ROOT / "samples" / "azure-mcp"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def test_server_params_pin_and_strip_azure_variables():
    params = server_params(
        {"PATH": "/usr/bin", "AZURE_CLIENT_SECRET": "x", "AZURE_TOKEN_CREDENTIALS": "dev"}, npx="/usr/bin/npx"
    )
    assert params.command == "/usr/bin/npx" and "@azure/mcp@3.0.0" in params.args and "--read-only" in params.args
    assert params.args.count("--namespace") == 7 and "compact" in params.args
    assert "AZURE_CLIENT_SECRET" not in params.env and params.env["AZURE_TOKEN_CREDENTIALS"] == "dev"
    with pytest.raises(FileNotFoundError):
        server_params({"PATH": "/nonexistent"}, npx=None)


def test_recorded_host_matches_arguments_and_wildcards():
    host = RecordedAzureMcpHost.from_directory(RECORDINGS)
    assert len(host.recordings) == 5

    async def run():
        groups = await host.call("group_list", {"subscription": SUBSCRIPTION})
        assert groups.server_version.startswith("3.0.0") and groups.protocol_version == "2026-07-28"
        assert len(groups.structured["groups"]) == 2
        retirement = await host.call(
            "advisor_recommendation_list",
            {
                "subscription": SUBSCRIPTION,
                "sub-category": "ServiceUpgradeAndRetirement",
                "retirement-date": "le:2099-01-01",
            },
        )
        assert len(retirement.structured["recommendations"]) == 1
        with pytest.raises(HostError, match="no recording"):
            await host.call("group_list", {"subscription": "00000000-0000-0000-0000-000000000009"})
        with pytest.raises(HostError, match="not on the host's allow-list"):
            await host.call("storage_account_create", {})
        with pytest.raises(HostError, match="no recording"):
            await host.call("pricing_get", {"service": "x"})  # allowed, but nothing recorded

    asyncio.run(run())
    assert [tool for tool, _ in host.calls] == [
        "group_list",
        "advisor_recommendation_list",
        "group_list",
        "pricing_get",
    ]
    with pytest.raises(HostError, match="no recordings"):
        RecordedAzureMcpHost.from_directory(ROOT / "docs")


def test_recording_matching_rules():
    recording = Recording("t", {"a": "1", "b": "*"}, None, "", "", "", "")
    assert recording.matches("t", {"a": "1", "b": "anything"})
    assert recording.matches("t", {"a": "1", "b": "x", "c": None})  # None arguments are not sent
    assert not recording.matches("t", {"a": "1"})
    assert not recording.matches("t", {"a": "2", "b": "x"})
    assert not recording.matches("u", {"a": "1", "b": "x"})


def test_evidence_from_result_hashes_parameters_and_names_the_tool():
    result = ToolResult(
        tool="group_list",
        arguments={"subscription": SUBSCRIPTION},
        structured={
            "groups": [
                {"id": f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-hcw-sample-prod", "name": "rg-hcw-sample-prod"}
            ]
        },
        text="1 group",
        server_name="Azure MCP Server",
        server_version="3.0.0+abc",
        protocol_version="2026-07-28",
    )
    record = evidence_from_result(result, identity_mode=IdentityMode.NONE, now=NOW, collection_run_id="run_1")
    assert record.kind.value == "azure-mcp-result" and record.evidenceClass.value == "observed"
    assert record.provenance.tool == "group_list" and record.provenance.serverVersion == "3.0.0+abc"
    assert record.provenance.parametersRedacted["subscription"].startswith("sha256:")
    assert SUBSCRIPTION not in record.provenance.parametersRedacted["subscription"]
    assert record.subject.subscriptionId == SUBSCRIPTION and record.collectionRunId == "run_1"
    assert record.payload["tool"] == "group_list" and len(record.payload["rows"]) == 1
    with pytest.raises(HostError, match="answered an error"):
        evidence_from_result(
            ToolResult("group_list", {}, None, "boom", "", "", "", is_error=True),
            identity_mode=IdentityMode.NONE,
            now=NOW,
        )
    unparsed = evidence_from_result(
        ToolResult("pricing_get", {"service": "x"}, None, "no structured content", "", "", ""),
        identity_mode=IdentityMode.NONE,
        now=NOW,
    )
    assert unparsed.payload == {"content": "no structured content"} and unparsed.subject.scope.value == "tenant"


def test_standard_sequence_names_five_read_only_calls():
    sequence = standard_sequence(SUBSCRIPTION, NOW)
    assert [tool for tool, _ in sequence] == [
        "subscription_list",
        "group_list",
        "advisor_recommendation_list",
        "advisor_recommendation_list",
        "policy_assignment_list",
    ]
    assert all(tool in ALLOWED_TOOLS for tool, _ in sequence)
    assert sequence[3][1]["retirement-date"] == "le:2027-04-19"


def test_collect_ingests_every_result_and_records_failures():
    ledger = InMemoryLedger()
    host = RecordedAzureMcpHost.from_directory(RECORDINGS)
    run = asyncio.run(collect(host, ledger, subscription_id=SUBSCRIPTION, actor_hash="sha256:abc", now=NOW))
    assert run.summary == {"evidence": 5, "rows": 7, "errors": 0} and run.errors == []
    assert len(ledger.evidence) == 5 and all(e.collectionRunId == run.runId for e in ledger.evidence.values())
    assert [s.tool for s in run.sources] == [tool for tool, _ in standard_sequence(SUBSCRIPTION, NOW)]
    assert run.scope.subscriptionId == SUBSCRIPTION and run.trigger == "operator"
    # a subscription nothing was recorded for: every call but subscription_list fails, the run says so by code
    failing = asyncio.run(
        collect(host, InMemoryLedger(), subscription_id="00000000-0000-0000-0000-000000000009", now=NOW)
    )
    assert failing.summary["evidence"] == 1 and failing.errors == ["no_recording"] * 4
    assert [s.status for s in failing.sources] == ["ok"] + ["no_recording"] * 4


def test_settings_select_the_host_mode():
    assert Settings.from_env({}).azmcp_mode == "off" and azure_connectivity("off") == "not-configured"
    assert Settings.from_env({"CC_AZMCP_MODE": "Recorded"}).azmcp_mode == "recorded"
    assert Settings.from_env({"CC_AZMCP_MODE": "stdio"}).azmcp_mode == "stdio"
    assert azure_connectivity("stdio") == "stdio-developer-credential" and azure_connectivity("recorded") == "recorded"
    assert Settings.from_env({"CC_AZMCP_RECORDINGS": " /tmp/x "}).azmcp_recordings == "/tmp/x"
    with pytest.raises(ValueError):
        Settings.from_env({"CC_AZMCP_MODE": "http"})
