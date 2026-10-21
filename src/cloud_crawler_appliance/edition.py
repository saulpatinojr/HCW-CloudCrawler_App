"""The App edition's startup guard.

This slice has no Azure MCP host and no collector, so the edition needs no identity yet. What it refuses already is
what it will always refuse: a secret-bearing credential variable in the environment. When the Azure MCP host arrives,
the identity it accepts is a managed identity or a delegated token forwarded per request, never a secret (website
proposal, section 8). The lab edition's stricter guard (no cloud SDK importable, refusal under an identity endpoint)
lives in HCW-CloudCrawler_AddOn.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

EDITION = "appliance"
AZURE_CONNECTIVITY = "not-configured"  # becomes "managed-identity" or "obo" once the Azure MCP host is wired
CAPABILITIES = ("evidence", "decisions", "drift", "proposals", "mcp")
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


def assert_appliance_ready(env: Mapping[str, str] | None = None) -> None:
    refuse_forbidden_env(env)
