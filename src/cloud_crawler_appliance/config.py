"""Settings from the environment (prefix CC_). Nothing secret is read here; the edition guard refuses secret-bearing
credential variables before this runs. Every key is listed in .env.example."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

# Upper bound for every numeric setting, so derived values (minutes * 60, bytes) stay representable.
MAX_SETTING = 1_000_000_000


def _int(env: Mapping[str, str], key: str, default: int, *, minimum: int = 0) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    if not raw.isdigit() or len(raw) > 10:
        raise ValueError(f"{key} must be an integer between {minimum} and {MAX_SETTING}")
    value = int(raw)
    if value < minimum or value > MAX_SETTING:
        raise ValueError(f"{key} must be between {minimum} and {MAX_SETTING}")
    return value


def _flag(env: Mapping[str, str], key: str, default: bool = False) -> bool:
    raw = env.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _hosts(env: Mapping[str, str], key: str) -> tuple[str, ...]:
    """Host header values (host or host:port), space or comma separated. No scheme, no path, no spaces inside."""
    raw = env.get(key, "").replace(",", " ")
    hosts = []
    for item in raw.split():
        if "/" in item or "@" in item:
            raise ValueError(f"{key} entries must be host names (host or host:port)")
        hosts.append(item.strip().lower())
    return tuple(dict.fromkeys(hosts))


AZMCP_MODES = ("off", "stdio", "recorded")


def _mode(env: Mapping[str, str], key: str) -> str:
    raw = env.get(key, "").strip().lower() or "off"
    if raw not in AZMCP_MODES:
        raise ValueError(f"{key} must be one of {', '.join(AZMCP_MODES)}")
    return raw


@dataclass(frozen=True)
class Settings:
    port: int = 8080
    log_silent: bool = False
    max_upload_bytes: int = 5 * 1024 * 1024
    max_rows: int = 5_000
    evidence_ttl_hours: int = 24
    # Host header values the MCP transport accepts (DNS-rebinding protection). Empty keeps the SDK's loopback default;
    # a deployment behind an ingress names its own FQDN here.
    allowed_hosts: tuple[str, ...] = ()
    # The Azure MCP host: off (no Azure tool exists), stdio (the development model: Azure MCP Server 3.0.0 as a child
    # process over stdio, the developer's own credential chain), recorded (replay the JSON recordings in a directory).
    azmcp_mode: str = "off"
    azmcp_recordings: str = "samples/azure-mcp"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        return cls(
            port=_int(env, "PORT", 8080, minimum=1),
            log_silent=_flag(env, "CC_LOG_SILENT"),
            max_upload_bytes=_int(env, "CC_MAX_UPLOAD_BYTES", 5 * 1024 * 1024, minimum=1),
            max_rows=_int(env, "CC_MAX_ROWS", 5_000, minimum=1),
            evidence_ttl_hours=_int(env, "CC_EVIDENCE_TTL_HOURS", 24, minimum=1),
            allowed_hosts=_hosts(env, "CC_ALLOWED_HOSTS"),
            azmcp_mode=_mode(env, "CC_AZMCP_MODE"),
            azmcp_recordings=env.get("CC_AZMCP_RECORDINGS", "").strip() or "samples/azure-mcp",
        )
