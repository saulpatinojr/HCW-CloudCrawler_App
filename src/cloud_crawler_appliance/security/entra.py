"""Microsoft Entra access-token validation for /api and /mcp (ADR 0004).

What it accepts: an RS256 JWT whose signature verifies against the tenant's published signing keys (JWKS), whose
issuer is the configured tenant's v2.0 or v1.0 issuer, whose audience is one of the configured values, whose `exp`
and `nbf` hold within a small declared clock skew, and whose `tid` is the configured tenant. Nothing else: `none`,
HMAC algorithms, other RSA variants, an unknown or missing `kid`, and a missing `exp`, `nbf`, `iss`, `aud`, `tid`
or `oid` are all refused.

What it keeps: a `Principal` (object id, tenant id, scopes, app roles, whether the token is app-only) on the request
scope. The token itself is never stored, forwarded or logged, and no claim value is logged: a failure is logged as a
status and an `AuthFailure` code, which is a fixed word. With `CC_AUTH_REQUIRED_ROLES` set, a valid token that carries
none of those app roles is refused with 403 (`AuthFailure.ROLE`) after every other check has passed.

The key fetcher is injectable so tests run with a locally generated key and no network. The default fetcher uses the
standard library over HTTPS only, with a timeout, a size cap and no redirects.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import anyio.to_thread
import jwt
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from cloud_crawler_appliance.config import Settings
from cloud_crawler_appliance.security import logging as logs

ENTRA_AUTHORITY = "https://login.microsoftonline.com"
V1_ISSUER_HOST = "https://sts.windows.net"
HEALTH_PATH = "/api/health"
PRINCIPAL_SCOPE_KEY = "cloud_crawler.principal"
ALGORITHM = "RS256"
MAX_TOKEN_CHARS = 16_384  # an Entra token with many claims is a few KB; anything near this is not one
MAX_JWKS_BYTES = 1_048_576
JWKS_FETCH_TIMEOUT_SECONDS = 5.0
JWKS_REFRESH_COOLDOWN_SECONDS = 30  # an unknown `kid` may trigger a refetch at most this often (no amplification)
MAX_STALE_FACTOR = 4  # cached keys are discarded when a refresh keeps failing for this many cache lifetimes
SERVICE_UNAVAILABLE_RETRY_SECONDS = 5
_TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9._~+/-]+=*$")
_REQUIRED_CLAIMS = ("exp", "nbf", "iss", "aud")


class AuthFailure(StrEnum):
    """Why a request was refused. Fixed words, so they are safe in a log line."""

    MISSING = "missing"
    MALFORMED = "malformed"
    ALGORITHM = "algorithm"
    KEY = "key"
    SIGNATURE = "signature"
    EXPIRED = "expired"
    NOT_YET_VALID = "not_yet_valid"
    AUDIENCE = "audience"
    ISSUER = "issuer"
    TENANT = "tenant"
    CLAIMS = "claims"
    ROLE = "role"
    UNAVAILABLE = "unavailable"


class AuthError(Exception):
    def __init__(self, failure: AuthFailure) -> None:
        super().__init__(failure.value)
        self.failure = failure


@dataclass(frozen=True)
class Principal:
    """The validated caller. `object_id` is the Entra `oid` (a person or a service principal)."""

    object_id: str
    tenant_id: str
    scopes: frozenset[str]
    app_only: bool
    roles: frozenset[str] = frozenset()  # the token's `roles` claim (app roles); empty when absent or malformed

    def is_person(self, required_scope: str) -> bool:
        """A signed-in person: a delegated token (it has `scp`) that carries the required scope and is not app-only."""
        return not self.app_only and required_scope in self.scopes


def principal_of(request: Any) -> Principal | None:
    """The principal the middleware validated for this request, or None (no request, or authentication is off)."""
    if request is None:
        return None
    value = request.scope.get(PRINCIPAL_SCOPE_KEY)
    return value if isinstance(value, Principal) else None


JwksFetcher = Callable[[str], dict[str, Any]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_jwks_over_https(url: str) -> dict[str, Any]:
    """GET the key set: https only, timeout, size cap, no redirects. Raises on anything but a 200 JSON object."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("the key set must be fetched over https")
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(request, timeout=JWKS_FETCH_TIMEOUT_SECONDS) as response:  # nosec B310 - https checked above
        if response.status != 200:
            raise ValueError("the key set request did not answer 200")
        body = response.read(MAX_JWKS_BYTES + 1)
    if len(body) > MAX_JWKS_BYTES:
        raise ValueError("the key set is too large")
    document = json.loads(body)
    if not isinstance(document, dict):
        raise ValueError("the key set is not a JSON object")
    return document


class JwksCache:
    """Signing keys by `kid`, refreshed when older than `ttl` seconds or on an unknown `kid` (rate limited)."""

    def __init__(
        self,
        url: str,
        fetcher: JwksFetcher,
        *,
        ttl: float,
        clock: Callable[[], float] = time.monotonic,
        cooldown: float = JWKS_REFRESH_COOLDOWN_SECONDS,
    ) -> None:
        self._url = url
        self._fetcher = fetcher
        self._ttl = ttl
        self._clock = clock
        self._cooldown = cooldown
        self._lock = threading.Lock()
        self._keys: dict[str, Any] = {}
        self._fetched_at: float | None = None
        self._attempted_at: float | None = None
        self._last_failed = False

    def _refresh(self, now: float) -> None:
        self._attempted_at = now
        try:
            key_set = jwt.PyJWKSet.from_dict(self._fetcher(self._url))
            keys = {
                k.key_id: k
                for k in key_set.keys
                if k.key_id and k.key_type == "RSA" and k.public_key_use in (None, "sig")
            }
            if not keys:
                raise ValueError("the key set holds no usable signing key")
        except Exception:  # noqa: BLE001 - any fetch or parse failure is the same to the caller: keys unavailable
            self._last_failed = True
            if self._fetched_at is not None and now - self._fetched_at > self._ttl * MAX_STALE_FACTOR:
                self._keys, self._fetched_at = {}, None
            return
        self._keys, self._fetched_at, self._last_failed = keys, now, False

    def key_for(self, kid: str) -> Any:
        with self._lock:
            now = self._clock()
            fresh = self._fetched_at is not None and now - self._fetched_at < self._ttl
            if not (fresh and kid in self._keys):
                cooled = self._attempted_at is None or now - self._attempted_at >= self._cooldown
                if cooled:
                    self._refresh(now)
            key = self._keys.get(kid)
            if key is not None:
                return key.key
            if self._last_failed or not self._keys:
                raise AuthError(AuthFailure.UNAVAILABLE)
            raise AuthError(AuthFailure.KEY)


class TokenVerifier:
    def __init__(
        self,
        settings: Settings,
        fetcher: JwksFetcher | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        tenant = settings.entra_tenant_id.lower()
        self._tenant = tenant
        self._audiences = list(settings.entra_audience)
        self._issuers = [f"{ENTRA_AUTHORITY}/{tenant}/v2.0", f"{V1_ISSUER_HOST}/{tenant}/"]
        self._skew = settings.entra_clock_skew_seconds
        self.human_scope = settings.entra_human_scope
        self.required_roles = frozenset(settings.auth_required_roles)
        self._cache = JwksCache(
            f"{ENTRA_AUTHORITY}/{tenant}/discovery/v2.0/keys",
            fetcher or fetch_jwks_over_https,
            ttl=settings.entra_jwks_cache_seconds,
            clock=clock,
        )

    def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise AuthError(AuthFailure.MALFORMED) from None
        if header.get("alg") != ALGORITHM:
            raise AuthError(AuthFailure.ALGORITHM)
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise AuthError(AuthFailure.KEY)
        key = self._cache.key_for(kid)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[ALGORITHM],
                audience=self._audiences,
                issuer=self._issuers,
                leeway=self._skew,
                options={"require": list(_REQUIRED_CLAIMS)},
            )
        except jwt.ExpiredSignatureError:
            raise AuthError(AuthFailure.EXPIRED) from None
        except jwt.ImmatureSignatureError:
            raise AuthError(AuthFailure.NOT_YET_VALID) from None
        except jwt.InvalidAudienceError:
            raise AuthError(AuthFailure.AUDIENCE) from None
        except jwt.InvalidIssuerError:
            raise AuthError(AuthFailure.ISSUER) from None
        except jwt.InvalidSignatureError:
            raise AuthError(AuthFailure.SIGNATURE) from None
        except jwt.MissingRequiredClaimError:
            raise AuthError(AuthFailure.CLAIMS) from None
        except jwt.PyJWTError:
            raise AuthError(AuthFailure.MALFORMED) from None
        return self._principal(claims)

    def _principal(self, claims: dict[str, Any]) -> Principal:
        tid, oid, scp = claims.get("tid"), claims.get("oid"), claims.get("scp", "")
        if not isinstance(tid, str) or tid.lower() != self._tenant:
            raise AuthError(AuthFailure.TENANT)
        if not isinstance(oid, str) or not oid.strip() or len(oid) > 64 or not isinstance(scp, str):
            raise AuthError(AuthFailure.CLAIMS)
        raw_roles = claims.get("roles")
        # A `roles` claim that is not a list of text counts as no roles: it never grants anything, so a deployment that
        # requires a role answers 403, and one that does not require a role never looks at the claim.
        valid = isinstance(raw_roles, list) and all(isinstance(r, str) for r in raw_roles)
        return Principal(
            object_id=oid.strip().lower(),
            tenant_id=self._tenant,
            scopes=frozenset(scp.split()),
            app_only=claims.get("idtyp") == "app" or not scp.strip(),
            roles=frozenset(raw_roles) if valid else frozenset(),
        )

    def authorize(self, principal: Principal) -> None:
        """Raises AuthError(ROLE) when roles are required and the token carries none of them (ADR 0004 amendment)."""
        if self.required_roles and not (principal.roles & self.required_roles):
            raise AuthError(AuthFailure.ROLE)


def _bearer_token(scope: Scope) -> str:
    """The token from exactly one `Authorization: Bearer` header; raises AuthError otherwise."""
    values = [v for k, v in scope["headers"] if k == b"authorization"]
    if not values:
        raise AuthError(AuthFailure.MISSING)
    if len(values) != 1:
        raise AuthError(AuthFailure.MALFORMED)
    scheme, _, token = values[0].decode("latin-1").partition(" ")
    if scheme.lower() != "bearer":
        raise AuthError(AuthFailure.MISSING)
    if not token or len(token) > MAX_TOKEN_CHARS or not _TOKEN_SHAPE.match(token):
        raise AuthError(AuthFailure.MALFORMED)
    return token


def _refusal(failure: AuthFailure) -> JSONResponse:
    common = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
    if failure is AuthFailure.UNAVAILABLE:
        body = {"error": {"code": "auth_unavailable", "message": "sign-in cannot be checked right now"}}
        return JSONResponse(
            body, status_code=503, headers={**common, "Retry-After": str(SERVICE_UNAVAILABLE_RETRY_SECONDS)}
        )
    if failure is AuthFailure.ROLE:
        # Generic on purpose: the body does not say which roles would have been enough.
        body = {"error": {"code": "forbidden", "message": "this identity is not allowed to use the service"}}
        return JSONResponse(body, status_code=403, headers=common)
    if failure is AuthFailure.MISSING:
        body = {"error": {"code": "unauthenticated", "message": "a bearer access token is required"}}
        return JSONResponse(body, status_code=401, headers={**common, "WWW-Authenticate": "Bearer"})
    body = {"error": {"code": "invalid_token", "message": "the access token is not valid"}}
    return JSONResponse(body, status_code=401, headers={**common, "WWW-Authenticate": 'Bearer error="invalid_token"'})


class EntraAuthMiddleware:
    """Pure ASGI (it must not buffer the MCP stream). Everything except `GET /api/health` needs a valid token."""

    def __init__(self, app: ASGIApp, verifier: TokenVerifier) -> None:
        self.app = app
        self.verifier = verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind == "lifespan" or (kind == "http" and scope["path"] == HEALTH_PATH):
            await self.app(scope, receive, send)
            return
        if kind != "http":  # no websocket route exists; refuse rather than guess
            await send({"type": "websocket.close", "code": 1008})
            return
        try:
            token = _bearer_token(scope)
            principal = await anyio.to_thread.run_sync(self.verifier.verify, token)
            self.verifier.authorize(principal)
        except AuthError as exc:
            status = {AuthFailure.UNAVAILABLE: 503, AuthFailure.ROLE: 403}.get(exc.failure, 401)
            logs.log_event("request_error", status=status, reason=exc.failure)
            await _refusal(exc.failure)(scope, receive, send)
            return
        scope[PRINCIPAL_SCOPE_KEY] = principal
        await self.app(scope, receive, send)
