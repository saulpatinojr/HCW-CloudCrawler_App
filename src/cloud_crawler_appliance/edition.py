"""The App edition's startup guard.

What it refuses is what it will always refuse: a secret-bearing credential variable in the environment. The Azure
MCP host, when configured, runs Azure MCP Server as a child process over stdio that authenticates with the
developer's own credential chain (the development model), or replays recordings; the appliance itself never holds a
token. The hosted identities (a managed identity, a delegated token forwarded per request) arrive with the HTTP
transport later (website proposal, section 8). The lab edition's stricter guard (no cloud SDK importable, refusal
under an identity endpoint) lives in HCW-CloudCrawler_AddOn.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

EDITION = "appliance"
AZURE_CONNECTIVITY = "not-configured"  # the default; `azure_connectivity` names the configured host mode
CONNECTIVITY_BY_MODE = {"off": AZURE_CONNECTIVITY, "stdio": "stdio-developer-credential", "recorded": "recorded"}
CAPABILITIES = ("evidence", "decisions", "drift", "proposals", "reviews", "mcp")
FORBIDDEN_ENV = (
    "AZURE_CLIENT_SECRET",
    "AZURE_CLIENT_CERTIFICATE_PATH",
    "AZURE_CLIENT_CERTIFICATE_PASSWORD",
    "AZURE_USERNAME",
    "AZURE_PASSWORD",
)


class EditionError(RuntimeError):
    """Raised when the appliance must not start. The message names a variable, never its value."""


def refuse_forbidden_env(env: Mapping[str, str] | None = None) -> None:
    env = os.environ if env is None else env
    present = [name for name in FORBIDDEN_ENV if env.get(name, "") != ""]
    if present:
        raise EditionError("secret-bearing credential variable present: " + ", ".join(present))


def azure_connectivity(mode: str) -> str:
    """What `/api/health` reports: never a credential, only how the host reaches Azure MCP."""
    return CONNECTIVITY_BY_MODE.get(mode, AZURE_CONNECTIVITY)


def assert_appliance_ready(env: Mapping[str, str] | None = None) -> None:
    refuse_forbidden_env(env)
