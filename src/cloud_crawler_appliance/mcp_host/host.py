"""Two hosts behind one interface: `StdioAzureMcpHost` starts the real server as a child process (the development
model); `RecordedAzureMcpHost` replays fictional results from JSON recordings (tests, demonstrations, and the shape
the website hands the lab edition). `evidence_from_result` is the result-to-evidence mapping both share: observed
evidence of kind `azure-mcp-result`, provenance naming the tool, server, version and protocol, the request
parameters as hashes, and the subject taken from the request's subscription."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from cloud_crawler_core.hashing import sha256_text
from cloud_crawler_core.ingest import ingest
from cloud_crawler_core.models import (
    Evidence,
    EvidenceClass,
    EvidenceKind,
    IdentityMode,
    ScopeKind,
    SourceProvenance,
    SourceType,
    Subject,
)
from mcp.client import Client

from cloud_crawler_appliance.mcp_host.contract import ALLOWED_TOOLS, PIN, server_params

WILDCARD = "*"


class HostError(RuntimeError):
    """A refusal or failure of the host. The message is content-free (a code and a tool name)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ToolResult:
    tool: str
    arguments: dict[str, Any]
    structured: Any
    text: str
    server_name: str
    server_version: str
    protocol_version: str
    is_error: bool = False


def _check_allowed(tool: str) -> None:
    if tool not in ALLOWED_TOOLS:
        raise HostError("tool_not_allowed", f"{tool} is not on the host's allow-list")


class AzureMcpHost:
    """The interface: `async with host: result = await host.call(tool, arguments)`."""

    identity_mode: IdentityMode = IdentityMode.NONE
    mode: str = "off"

    async def __aenter__(self) -> AzureMcpHost:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def call(self, tool: str, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError


class StdioAzureMcpHost(AzureMcpHost):
    """The development model: Azure MCP as a child process over stdio, authenticating with the developer's own
    credential chain. Nothing passes through the appliance but tool calls and results."""

    mode = "stdio"

    def __init__(self, env: dict[str, str] | None = None, *, read_timeout_seconds: float = 180) -> None:
        self._params = server_params(env)
        self._timeout = read_timeout_seconds
        self._client: Client | None = None

    async def __aenter__(self) -> StdioAzureMcpHost:
        client = Client(self._params, read_timeout_seconds=self._timeout)
        await client.__aenter__()
        info = client.server_info
        if info is None or not info.version.startswith(PIN):
            await client.__aexit__(None, None, None)
            raise HostError("server_version", f"Azure MCP Server is not {PIN}")
        self._client = client
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None

    async def call(self, tool: str, arguments: dict[str, Any]) -> ToolResult:
        _check_allowed(tool)
        if self._client is None:
            raise HostError("not_open", "the host is not open")
        result = await self._client.call_tool(tool, arguments)
        info = self._client.server_info
        return ToolResult(
            tool=tool,
            arguments=dict(arguments),
            structured=result.structured_content,
            text="".join(getattr(c, "text", "") for c in result.content),
            server_name=info.name if info else "",
            server_version=info.version if info else "",
            protocol_version=self._client.protocol_version or "",
            is_error=bool(result.is_error),
        )


@dataclass
class Recording:
    tool: str
    arguments: dict[str, Any]
    structured: Any
    text: str
    server_name: str
    server_version: str
    protocol_version: str

    @classmethod
    def from_file(cls, path: Path) -> Recording:
        data = json.loads(path.read_text(encoding="utf-8"))
        info = data.get("serverInfo") or {}
        return cls(
            tool=data["tool"],
            arguments=dict(data.get("arguments") or {}),
            structured=data.get("structuredContent"),
            text=str(data.get("content", "")),
            server_name=str(info.get("name", "")),
            server_version=str(info.get("version", "")),
            protocol_version=str(data.get("protocolVersion", "")),
        )

    def matches(self, tool: str, arguments: dict[str, Any]) -> bool:
        if self.tool != tool:
            return False
        given = {k: v for k, v in arguments.items() if v is not None}
        if set(given) != set(self.arguments):
            return False
        return all(expected == WILDCARD or given[key] == expected for key, expected in self.arguments.items())


@dataclass
class RecordedAzureMcpHost(AzureMcpHost):
    """Replays recordings (`samples/azure-mcp/*.json`): the same allow-list, the same result shape, no process."""

    recordings: list[Recording] = field(default_factory=list)
    mode: str = "recorded"
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    @classmethod
    def from_directory(cls, directory: Path) -> RecordedAzureMcpHost:
        files = sorted(directory.glob("*.json"))
        if not files:
            raise HostError("no_recordings", "the recordings directory holds no recordings")
        return cls(recordings=[Recording.from_file(p) for p in files])

    async def call(self, tool: str, arguments: dict[str, Any]) -> ToolResult:
        _check_allowed(tool)
        self.calls.append((tool, dict(arguments)))
        for recording in self.recordings:
            if recording.matches(tool, arguments):
                return ToolResult(
                    tool=tool,
                    arguments=dict(arguments),
                    structured=recording.structured,
                    text=recording.text,
                    server_name=recording.server_name,
                    server_version=recording.server_version,
                    protocol_version=recording.protocol_version,
                )
        raise HostError("no_recording", f"no recording matches {tool} with these arguments")


def evidence_from_result(
    result: ToolResult,
    *,
    identity_mode: IdentityMode,
    now: datetime,
    collection_run_id: str | None = None,
    max_rows: int = 5_000,
    actor_hash: str | None = None,
    ttl_override: timedelta | None = None,
) -> Evidence:
    """Observed evidence from one result: the structured content is hashed, redacted and normalised by the tool."""
    if result.is_error:
        raise HostError("tool_error", f"{result.tool} answered an error")
    subscription = result.arguments.get("subscription")
    subject = Subject(
        scope=ScopeKind.SUBSCRIPTION if subscription else ScopeKind.TENANT,
        subscriptionId=str(subscription).lower() if subscription else None,
    )
    provenance = SourceProvenance(
        sourceType=SourceType.AZURE_MCP,
        tool=result.tool,
        serverName=result.server_name or None,
        serverVersion=result.server_version or None,
        protocolVersion=result.protocol_version or None,
        parametersRedacted={k: sha256_text(json.dumps(v, sort_keys=True)) for k, v in result.arguments.items()},
        identityMode=identity_mode,
        actorId=actor_hash,
    )
    return ingest(
        kind=EvidenceKind.AZURE_MCP_RESULT,
        evidence_class=EvidenceClass.OBSERVED,
        payload=result.structured if result.structured is not None else {"content": result.text},
        subject=subject,
        provenance=provenance,
        authenticated=True,
        now=now,
        collection_run_id=collection_run_id,
        max_rows=max_rows,
        ttl_override=ttl_override,
    )
