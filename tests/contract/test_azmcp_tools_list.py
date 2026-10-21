"""The Azure MCP Server 3.0.0 contract this repository depends on (ADR 0001).

Starts the real server through `npx @azure/mcp@3.0.0` over stdio with the namespaces the design uses, sends only
`initialize` and `tools/list` (no Azure sign-in, no Azure call), and compares the tool names, input schemas, output
schemas and annotations with the committed snapshot. A changed snapshot means the pin moved or upstream changed a
contract; either is a reviewed change, never a silent one. Regenerate with CC_UPDATE_SNAPSHOT=1, locally only.

Marked `azmcp`: excluded from the default run (pyproject addopts), run by `make test-contract` and the CI job.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from cloud_crawler_appliance.mcp_host.contract import ALLOWED_TOOLS, PIN, server_params

SNAPSHOT = Path(__file__).with_name("snapshots") / f"azmcp-{PIN}-tools.json"

pytestmark = pytest.mark.azmcp


def _params() -> StdioServerParameters:
    """The host's own start command (`mcp_host.contract.server_params`), with a credential class that never prompts
    and is never exercised: only `initialize` and `tools/list` are sent."""
    if shutil.which("npx") is None:
        pytest.skip("npx is not on PATH; Node.js 22 is needed for the contract test")
    env = {k: v for k, v in os.environ.items() if not k.startswith("AZURE_")}
    env["AZURE_TOKEN_CREDENTIALS"] = "ManagedIdentityCredential"
    return server_params(env)


def _snapshot_of(tools) -> dict:
    out = {}
    for tool in sorted(tools, key=lambda t: t.name):
        annotations = tool.annotations.model_dump(mode="json", exclude_none=True) if tool.annotations else {}
        out[tool.name] = {
            "inputSchema": tool.input_schema,
            "outputSchema": tool.output_schema,
            "annotations": annotations,
        }
    return out


def test_tools_list_matches_the_pinned_snapshot():
    async def run():
        async with Client(_params(), read_timeout_seconds=180) as client:
            assert client.server_info is not None
            assert client.server_info.version.startswith(PIN), client.server_info.version
            listed = await client.list_tools()
            return client.server_info.version, _snapshot_of(listed.tools)

    version, current = asyncio.run(run())
    if os.environ.get("CC_UPDATE_SNAPSHOT") == "1" and os.environ.get("CI") != "true":
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps({"serverVersion": version, "tools": current}, indent=2, sort_keys=True) + "\n")
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert expected["serverVersion"].startswith(PIN)
    assert set(current) == set(expected["tools"]), sorted(set(current) ^ set(expected["tools"]))
    for name, tool in current.items():
        assert tool == expected["tools"][name], f"contract of {name} changed"
    # every tool on the host's allow-list exists, is read-only and needs no elicitation (not secret, not destructive)
    for name in sorted(ALLOWED_TOOLS):
        assert name in current, f"{name} is on the allow-list but not in the pinned tool list"
        annotations = current[name]["annotations"]  # the SDK dumps the hints in snake_case
        assert annotations.get("read_only_hint") is True and annotations.get("destructive_hint") is False, name
