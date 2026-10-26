"""Settings from the environment (prefix CC_). Nothing secret is read here; the edition guard refuses secret-bearing
credential variables before this runs. Every key is listed in .env.example."""

from __future__ import annotations

import ipaddress
import os
import re
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


AUTH_MODES = ("off", "entra")
DEFAULT_HUMAN_SCOPE = "access_as_user"
DEFAULT_CLOCK_SKEW_SECONDS = 60
MAX_CLOCK_SKEW_SECONDS = 300
DEFAULT_JWKS_CACHE_SECONDS = 900
MIN_JWKS_CACHE_SECONDS = 60
MAX_JWKS_CACHE_SECONDS = 86_400
LOOPBACK_BIND_HOST = "127.0.0.1"
_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_SCOPE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
ENTRA_KEYS = (
    "CC_ENTRA_TENANT_ID",
    "CC_ENTRA_AUDIENCE",
    "CC_ENTRA_HUMAN_SCOPE",
    "CC_ENTRA_CLOCK_SKEW_SECONDS",
    "CC_ENTRA_JWKS_CACHE_SECONDS",
    "CC_AUTH_REQUIRED_ROLES",
)
# The loud opt-out that lets sign-in stay off on a non-loopback address (ADR 0004, amendment 2026-10-26).
ALLOW_UNAUTHENTICATED_KEY = "CC_ALLOW_UNAUTHENTICATED_NON_LOOPBACK"
MAX_ROLES = 32


def _auth_mode(env: Mapping[str, str], key: str) -> str:
    raw = env.get(key, "").strip().lower() or "off"
    if raw not in AUTH_MODES:
        raise ValueError(f"{key} must be one of {', '.join(AUTH_MODES)}")
    return raw


def _audiences(env: Mapping[str, str], key: str) -> tuple[str, ...]:
    """Accepted `aud` values (an application id URI or a client id), space or comma separated."""
    values = []
    for item in env.get(key, "").replace(",", " ").split():
        if len(item) > 256 or any(ord(c) < 33 or ord(c) > 126 for c in item):
            raise ValueError(f"{key} entries must be printable text without spaces, at most 256 characters")
        values.append(item)
    return tuple(dict.fromkeys(values))


def _roles(env: Mapping[str, str], key: str) -> tuple[str, ...]:
    """App role values a token must carry one of, comma or space separated (an Entra role value has no spaces)."""
    values = []
    for item in env.get(key, "").replace(",", " ").split():
        if len(item) > 128 or any(ord(c) < 33 or ord(c) > 126 for c in item):
            raise ValueError(f"{key} entries must be printable text without spaces, at most 128 characters")
        values.append(item)
    roles = tuple(dict.fromkeys(values))
    if len(roles) > MAX_ROLES:
        raise ValueError(f"{key} may list at most {MAX_ROLES} roles")
    return roles


def _bind_host(env: Mapping[str, str], key: str) -> str:
    raw = env.get(key, "").strip()
    if not raw:
        return LOOPBACK_BIND_HOST
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        raise ValueError(f"{key} must be an IP address such as 127.0.0.1 or 0.0.0.0") from None


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
    # Who may call /api and /mcp. off: nobody is asked (the lab default; /api/health is open in both modes).
    # entra: every route except /api/health needs a valid Microsoft Entra access token for the tenant and audience
    # below, and the human-only tools take the actor from the token (ADR 0004).
    auth_mode: str = "off"
    entra_tenant_id: str = ""
    entra_audience: tuple[str, ...] = ()
    entra_human_scope: str = DEFAULT_HUMAN_SCOPE
    entra_clock_skew_seconds: int = DEFAULT_CLOCK_SKEW_SECONDS
    entra_jwks_cache_seconds: int = DEFAULT_JWKS_CACHE_SECONDS
    # The interface uvicorn binds. Loopback unless the deployment says otherwise (the container image sets 0.0.0.0).
    bind_host: str = LOOPBACK_BIND_HOST
    # Entra only. App role values (the token's `roles` claim) of which a caller needs at least one, or the request is
    # answered 403. Empty (the default) means no role check, the behaviour before this setting existed.
    auth_required_roles: tuple[str, ...] = ()
    # Off only. The appliance refuses to start with sign-in off on a non-loopback address unless this is true.
    allow_unauthenticated_non_loopback: bool = False

    def __post_init__(self) -> None:
        if self.auth_mode not in AUTH_MODES:
            raise ValueError(f"CC_AUTH_MODE must be one of {', '.join(AUTH_MODES)}")
        if self.auth_mode == "off":
            if self.auth_required_roles:
                raise ValueError("CC_AUTH_REQUIRED_ROLES needs CC_AUTH_MODE=entra (a role check needs a token)")
            if not self.allow_unauthenticated_non_loopback and not ipaddress.ip_address(self.bind_host).is_loopback:
                raise ValueError(
                    f"CC_AUTH_MODE=off on the non-loopback address {self.bind_host} would answer anyone who can reach "
                    f"the port: set CC_AUTH_MODE=entra, bind {LOOPBACK_BIND_HOST}, or (lab only) set "
                    f"{ALLOW_UNAUTHENTICATED_KEY}=true"
                )
        if self.auth_mode == "entra":
            if not _GUID.match(self.entra_tenant_id):
                raise ValueError("CC_AUTH_MODE=entra needs CC_ENTRA_TENANT_ID set to the tenant (directory) id")
            if not self.entra_audience:
                raise ValueError("CC_AUTH_MODE=entra needs CC_ENTRA_AUDIENCE set to the accepted audience value(s)")
            if not _SCOPE.match(self.entra_human_scope):
                raise ValueError("CC_ENTRA_HUMAN_SCOPE must be a scope name such as access_as_user")
            if not 0 <= self.entra_clock_skew_seconds <= MAX_CLOCK_SKEW_SECONDS:
                raise ValueError(f"CC_ENTRA_CLOCK_SKEW_SECONDS must be between 0 and {MAX_CLOCK_SKEW_SECONDS}")
            if not MIN_JWKS_CACHE_SECONDS <= self.entra_jwks_cache_seconds <= MAX_JWKS_CACHE_SECONDS:
                raise ValueError(
                    f"CC_ENTRA_JWKS_CACHE_SECONDS must be between {MIN_JWKS_CACHE_SECONDS} and {MAX_JWKS_CACHE_SECONDS}"
                )
            if self.allow_unauthenticated_non_loopback:
                raise ValueError(f"{ALLOW_UNAUTHENTICATED_KEY} is only for CC_AUTH_MODE=off; remove it")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        auth_mode = _auth_mode(env, "CC_AUTH_MODE")
        stray = [key for key in ENTRA_KEYS if auth_mode == "off" and env.get(key, "").strip()]
        if stray:
            # Entra settings with authentication off would leave the operator believing the routes are protected.
            raise ValueError("Entra settings are present but CC_AUTH_MODE is off: " + ", ".join(stray))
        allow = _flag(env, ALLOW_UNAUTHENTICATED_KEY)
        return cls(
            port=_int(env, "PORT", 8080, minimum=1),
            log_silent=_flag(env, "CC_LOG_SILENT"),
            max_upload_bytes=_int(env, "CC_MAX_UPLOAD_BYTES", 5 * 1024 * 1024, minimum=1),
            max_rows=_int(env, "CC_MAX_ROWS", 5_000, minimum=1),
            evidence_ttl_hours=_int(env, "CC_EVIDENCE_TTL_HOURS", 24, minimum=1),
            allowed_hosts=_hosts(env, "CC_ALLOWED_HOSTS"),
            azmcp_mode=_mode(env, "CC_AZMCP_MODE"),
            azmcp_recordings=env.get("CC_AZMCP_RECORDINGS", "").strip() or "samples/azure-mcp",
            auth_mode=auth_mode,
            entra_tenant_id=env.get("CC_ENTRA_TENANT_ID", "").strip(),
            entra_audience=_audiences(env, "CC_ENTRA_AUDIENCE"),
            entra_human_scope=env.get("CC_ENTRA_HUMAN_SCOPE", "").strip() or DEFAULT_HUMAN_SCOPE,
            entra_clock_skew_seconds=_int(env, "CC_ENTRA_CLOCK_SKEW_SECONDS", DEFAULT_CLOCK_SKEW_SECONDS, minimum=0),
            entra_jwks_cache_seconds=_int(
                env, "CC_ENTRA_JWKS_CACHE_SECONDS", DEFAULT_JWKS_CACHE_SECONDS, minimum=MIN_JWKS_CACHE_SECONDS
            ),
            bind_host=_bind_host(env, "CC_BIND_HOST"),
            auth_required_roles=_roles(env, "CC_AUTH_REQUIRED_ROLES"),
            allow_unauthenticated_non_loopback=allow,
        )
