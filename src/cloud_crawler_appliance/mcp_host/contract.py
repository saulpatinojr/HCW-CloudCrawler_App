"""The Azure MCP Server contract the host depends on (ADR 0001): the pinned version, the namespaces, the read-only
tool allow-list, and the stdio start command the contract test and the development host share."""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping

from mcp.client.stdio import StdioServerParameters

PIN = "3.0.0"
NAMESPACES = ("advisor", "pricing", "policy", "group", "subscription", "wellarchitectedframework", "cloudarchitect")

# Every tool the appliance may call. All are read-only, non-destructive and need no elicitation (the contract test
# proves it against the pinned snapshot). A name outside this set is refused by the host before any request.
ALLOWED_TOOLS = frozenset(
    {
        "subscription_list",
        "group_list",
        "group_resource_list",
        "advisor_recommendation_list",
        "advisor_recommendation_summary",
        "advisor_metadata_list",
        "advisor_metadata_get",
        "advisor_remediation_get",
        "policy_assignment_list",
        "pricing_get",
        "wellarchitectedframework_serviceguide_get",
        "cloudarchitect_design",
    }
)


def server_params(env: Mapping[str, str] | None = None, *, npx: str | None = None) -> StdioServerParameters:
    """`npx @azure/mcp@3.0.0 server start --read-only --mode all --namespace ... --structured-output-mode compact`.

    `AZURE_*` variables are not passed through, so the child never sees a secret-bearing variable even if one were
    present; `AZURE_TOKEN_CREDENTIALS` is set by the caller (the contract test pins a credential class that never
    prompts and is never exercised; the development host leaves the developer's own chain)."""
    env = dict(os.environ if env is None else env)
    command = npx or shutil.which("npx", path=env.get("PATH"))
    if command is None:
        raise FileNotFoundError("npx is not on PATH; Node.js 22 is needed to start Azure MCP Server")
    args = [
        "-y",
        f"@azure/mcp@{PIN}",
        "server",
        "start",
        "--read-only",
        "--mode",
        "all",
        "--structured-output-mode",
        "compact",
    ]
    for namespace in NAMESPACES:
        args += ["--namespace", namespace]
    child_env = {k: v for k, v in env.items() if not k.startswith("AZURE_") or k == "AZURE_TOKEN_CREDENTIALS"}
    return StdioServerParameters(command=command, args=args, env=child_env)
