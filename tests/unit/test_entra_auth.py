"""Microsoft Entra token validation (ADR 0004), with no network and no real tenant.

An RSA key is generated when the tests start, its public half is served as a local key set through the injectable
fetcher, and every token is minted here. Placeholder identifiers only (`00000000-0000-0000-0000-0000000000NN`).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
import urllib.request
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import jwt
import pytest
from cloud_crawler_core.hashing import sha256_text
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from cloud_crawler_appliance.api import create_app
from cloud_crawler_appliance.config import Settings
from cloud_crawler_appliance.security import entra
from cloud_crawler_appliance.security.entra import AuthError, AuthFailure, EntraAuthMiddleware, JwksCache, TokenVerifier

TENANT = "00000000-0000-0000-0000-000000000002"
OTHER_TENANT = "00000000-0000-0000-0000-000000000009"
AUDIENCE = "api://00000000-0000-0000-0000-000000000003"
CLIENT_ID = "00000000-0000-0000-0000-000000000003"
PERSON = "00000000-0000-0000-0000-000000000021"
OTHER_PERSON = "00000000-0000-0000-0000-000000000022"
SERVICE = "00000000-0000-0000-0000-000000000023"
KID = "test-key-1"
ISSUER_V2 = f"https://login.microsoftonline.com/{TENANT}/v2.0"
ISSUER_V1 = f"https://sts.windows.net/{TENANT}/"
ENTRA_ENV = {
    "CC_AUTH_MODE": "entra",
    "CC_ENTRA_TENANT_ID": TENANT,
    "CC_ENTRA_AUDIENCE": f"{AUDIENCE} {CLIENT_ID}",
    "CC_LOG_SILENT": "1",
    "CC_ALLOWED_HOSTS": "testserver 127.0.0.1:* localhost:*",
}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Signer:
    """A key pair generated now, its key set document, and a token minter."""

    def __init__(self, kid: str = KID) -> None:
        self.kid = kid
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.private_pem = self.private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        self.public_pem = self.private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.private.public_key()))
        self.jwk = {**jwk, "kid": kid, "use": "sig", "alg": "RS256"}

    def claims(self, **overrides: Any) -> dict[str, Any]:
        now = int(time.time())
        base: dict[str, Any] = {
            "iss": ISSUER_V2,
            "aud": AUDIENCE,
            "tid": TENANT,
            "oid": PERSON,
            "sub": "subject-not-used",
            "scp": "access_as_user",
            "iat": now,
            "nbf": now,
            "exp": now + 3600,
        }
        base.update(overrides)
        return {k: v for k, v in base.items() if v is not None}

    def mint(self, *, headers: dict[str, Any] | None = None, **overrides: Any) -> str:
        header = {"kid": self.kid, **(headers or {})}
        return jwt.encode(self.claims(**overrides), self.private_pem, algorithm="RS256", headers=header)


@pytest.fixture(scope="module")
def signer() -> Signer:
    return Signer()


@pytest.fixture(scope="module")
def stranger() -> Signer:
    """A second key pair under the same kid: tokens it signs must not verify against the tenant's key set."""
    return Signer()


class FakeJwks:
    def __init__(self, *signers: Signer) -> None:
        self.keys = [s.jwk for s in signers]
        self.calls = 0
        self.fail = False

    def __call__(self, url: str) -> dict[str, Any]:
        self.calls += 1
        assert url == f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys"
        if self.fail:
            raise OSError("key set unreachable")
        return {"keys": list(self.keys)}


@pytest.fixture
def jwks(signer) -> FakeJwks:
    return FakeJwks(signer)


@pytest.fixture
def app(jwks):
    return create_app(Settings.from_env(ENTRA_ENV), env=ENTRA_ENV, jwks_fetcher=jwks)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def verifier(jwks: Callable, clock: Callable[[], float] = time.monotonic, **env: str) -> TokenVerifier:
    return TokenVerifier(Settings.from_env({**ENTRA_ENV, **env}), jwks, clock)


# ------------------------------------------------------------------------------------------------ settings


def test_default_is_off_and_health_says_so(quiet_env):
    settings = Settings.from_env(quiet_env)
    assert settings.auth_mode == "off" and settings.bind_host == "127.0.0.1"
    with TestClient(create_app(settings, env=quiet_env)) as c:
        assert c.get("/api/health").json()["auth"] == "off"
        # sign-in off: nothing asks for a token (the lab default, unchanged)
        assert c.get("/api/nope").status_code == 404


def test_entra_settings_are_read_from_the_environment():
    settings = Settings.from_env({**ENTRA_ENV, "CC_ENTRA_HUMAN_SCOPE": "approve", "CC_ENTRA_CLOCK_SKEW_SECONDS": "30"})
    assert settings.auth_mode == "entra" and settings.entra_tenant_id == TENANT
    assert settings.entra_audience == (AUDIENCE, CLIENT_ID) and settings.entra_human_scope == "approve"
    assert settings.entra_clock_skew_seconds == 30 and settings.entra_jwks_cache_seconds == 900


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"CC_ENTRA_TENANT_ID": ""}, "CC_ENTRA_TENANT_ID"),
        ({"CC_ENTRA_TENANT_ID": "contoso.onmicrosoft.com"}, "CC_ENTRA_TENANT_ID"),
        ({"CC_ENTRA_AUDIENCE": ""}, "CC_ENTRA_AUDIENCE"),
        ({"CC_ENTRA_AUDIENCE": "bad\x7faud"}, "CC_ENTRA_AUDIENCE"),
        ({"CC_ENTRA_HUMAN_SCOPE": "two words"}, "CC_ENTRA_HUMAN_SCOPE"),
        ({"CC_ENTRA_CLOCK_SKEW_SECONDS": "301"}, "CC_ENTRA_CLOCK_SKEW_SECONDS"),
        ({"CC_ENTRA_JWKS_CACHE_SECONDS": "59"}, "CC_ENTRA_JWKS_CACHE_SECONDS"),
        ({"CC_ENTRA_JWKS_CACHE_SECONDS": "86401"}, "CC_ENTRA_JWKS_CACHE_SECONDS"),
        ({"CC_AUTH_MODE": "oauth"}, "CC_AUTH_MODE"),
    ],
)
def test_entra_mode_refuses_to_start_on_a_missing_or_bad_setting(change, message):
    with pytest.raises(ValueError, match=message):
        Settings.from_env({**ENTRA_ENV, **change})


def test_entra_settings_with_sign_in_off_are_refused_not_ignored():
    with pytest.raises(ValueError, match="CC_ENTRA_TENANT_ID, CC_ENTRA_AUDIENCE"):
        Settings.from_env({"CC_ENTRA_TENANT_ID": TENANT, "CC_ENTRA_AUDIENCE": AUDIENCE})
    with pytest.raises(ValueError, match="CC_AUTH_MODE must be one of"):
        Settings(auth_mode="none")


def test_bind_host_must_be_an_ip_address():
    assert Settings.from_env({"CC_BIND_HOST": "0.0.0.0"}).bind_host == "0.0.0.0"  # noqa: S104
    with pytest.raises(ValueError, match="CC_BIND_HOST"):
        Settings.from_env({"CC_BIND_HOST": "example.test"})


# ------------------------------------------------------------------------------- routes: refused and open


def test_health_stays_open_and_flat_without_a_token(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] and body["version"] and body["edition"] == "appliance" and body["auth"] == "entra"
    assert TENANT not in response.text and AUDIENCE not in response.text  # nothing about the tenant is published


def test_the_health_path_is_exempt_whatever_the_method_and_leaks_nothing(client):
    # only the exact path is open, and it only ever answers GET; any other method gets the router's own 405
    assert client.post("/api/health").status_code == 405


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/nope"),
        ("GET", "/api/health/"),
        ("GET", "/mcp"),
        ("POST", "/mcp"),
        ("DELETE", "/mcp"),
        ("GET", "/elsewhere"),
    ],
)
def test_every_route_but_health_answers_401_without_a_token(client, method, path):
    response = client.request(method, path, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Cache-Control"] == "no-store" and response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.json() == {"error": {"code": "unauthenticated", "message": "a bearer access token is required"}}


def test_mcp_tools_list_is_refused_without_a_token_and_answers_with_one(client, signer):
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    accept = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    assert client.post("/mcp", json=rpc, headers=accept).status_code == 401
    allowed = client.post("/mcp", json=rpc, headers={**accept, **bearer(signer.mint())})
    assert allowed.status_code != 401 and "invalid_token" not in allowed.text


def test_a_valid_token_reaches_the_routes_behind_the_gate(client, signer):
    assert client.get("/api/nope", headers=bearer(signer.mint())).json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Bearer",
        "Bearer ",
        "Basic dXNlcjpwYXNz",
        "Bearer not.a.jwt!",
        "Bearer " + "a" * (entra.MAX_TOKEN_CHARS + 1),
        "Bearer one two",
        "bearer abc",  # the scheme is case-insensitive; this token is simply not a JWT
    ],
)
def test_missing_or_malformed_authorization_headers_are_401(client, header):
    response = client.get("/api/nope", headers={"Authorization": header})
    assert response.status_code == 401 and response.headers["WWW-Authenticate"].startswith("Bearer")


def test_two_authorization_headers_are_refused(client, signer):
    token = signer.mint()
    response = client.get("/api/nope", headers=[("Authorization", f"Bearer {token}"), ("Authorization", "Bearer x")])
    assert response.status_code == 401 and response.json()["error"]["code"] == "invalid_token"


def _forge_hs256(signer: Signer, claims: dict[str, Any]) -> str:
    """The classic confusion attack: HMAC-SHA256 keyed with the RSA public key's PEM text."""
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
    body = _b64(json.dumps(claims).encode())
    sig = hmac.new(signer.public_pem, f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{_b64(sig)}"


def _raw_rs256(signer: Signer, header: dict[str, Any], claims: dict[str, Any]) -> str:
    """Signs by hand, so a header the library would refuse to write (a numeric kid) can still be tested."""
    signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
    signature = signer.private.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64(signature)}"


def _alg_none(signer: Signer, claims: dict[str, Any]) -> str:
    head = _b64(json.dumps({"alg": "none", "typ": "JWT", "kid": KID}).encode())
    return f"{head}.{_b64(json.dumps(claims).encode())}."


def _token_cases(signer: Signer, stranger: Signer) -> list[tuple[str, str, AuthFailure]]:
    now = int(time.time())
    good = signer.claims()
    return [
        ("expired", signer.mint(exp=now - 3600, nbf=now - 7200), AuthFailure.EXPIRED),
        ("expired just beyond the skew", signer.mint(exp=now - 120), AuthFailure.EXPIRED),
        ("not yet valid", signer.mint(nbf=now + 3600, exp=now + 7200), AuthFailure.NOT_YET_VALID),
        ("not yet valid beyond the skew", signer.mint(nbf=now + 120), AuthFailure.NOT_YET_VALID),
        ("wrong audience", signer.mint(aud="api://00000000-0000-0000-0000-000000000099"), AuthFailure.AUDIENCE),
        ("audience missing", signer.mint(aud=None), AuthFailure.CLAIMS),
        ("wrong issuer", signer.mint(iss="https://evil.example/" + TENANT + "/v2.0"), AuthFailure.ISSUER),
        (
            "issuer of another tenant",
            signer.mint(iss=f"https://login.microsoftonline.com/{OTHER_TENANT}/v2.0"),
            AuthFailure.ISSUER,
        ),
        ("wrong tenant claim", signer.mint(tid=OTHER_TENANT), AuthFailure.TENANT),
        ("tenant claim missing", signer.mint(tid=None), AuthFailure.TENANT),
        ("tenant claim not text", signer.mint(tid=7), AuthFailure.TENANT),
        ("object id missing", signer.mint(oid=None), AuthFailure.CLAIMS),
        ("object id empty", signer.mint(oid="  "), AuthFailure.CLAIMS),
        ("object id too long", signer.mint(oid="x" * 65), AuthFailure.CLAIMS),
        ("scp not text", signer.mint(scp=["access_as_user"]), AuthFailure.CLAIMS),
        ("exp not a number", signer.mint(exp="soon"), AuthFailure.MALFORMED),
        ("exp missing", signer.mint(exp=None), AuthFailure.CLAIMS),
        ("nbf missing", signer.mint(nbf=None), AuthFailure.CLAIMS),
        ("unknown kid", signer.mint(headers={"kid": "rotated-away"}), AuthFailure.KEY),
        ("kid missing", jwt.encode(good, signer.private_pem, algorithm="RS256"), AuthFailure.KEY),
        ("kid not text", _raw_rs256(signer, {"alg": "RS256", "kid": 5}, good), AuthFailure.MALFORMED),
        ("signed by another key", stranger.mint(), AuthFailure.SIGNATURE),
        ("alg none", _alg_none(signer, good), AuthFailure.ALGORITHM),
        ("HS256 keyed with the public key", _forge_hs256(signer, good), AuthFailure.ALGORITHM),
        (
            "RS384 (another RSA variant)",
            jwt.encode(good, signer.private_pem, algorithm="RS384", headers={"kid": KID}),
            AuthFailure.ALGORITHM,
        ),
        ("not a JWT at all", "abc.def.ghi", AuthFailure.MALFORMED),
        ("tampered payload", _tamper(signer.mint()), AuthFailure.SIGNATURE),
    ]


def _tamper(token: str) -> str:
    head, body, sig = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    claims["oid"] = OTHER_PERSON
    return f"{head}.{_b64(json.dumps(claims).encode())}.{sig}"


def test_the_verifier_names_the_reason_for_every_refusal(signer, stranger, jwks):
    v = verifier(jwks)
    for name, token, failure in _token_cases(signer, stranger):
        with pytest.raises(AuthError) as raised:
            v.verify(token)
        assert raised.value.failure is failure, name


def test_http_answers_the_same_401_for_every_kind_of_invalid_token(client, signer, stranger):
    bodies = set()
    for name, token, _ in _token_cases(signer, stranger):
        response = client.get("/api/nope", headers=bearer(token))
        assert response.status_code == 401, name
        assert response.headers["WWW-Authenticate"] == 'Bearer error="invalid_token"', name
        bodies.add(response.text)
    # no oracle: the response never says which check failed
    assert bodies == {'{"error":{"code":"invalid_token","message":"the access token is not valid"}}'}


def test_a_valid_token_is_accepted_in_each_supported_form(signer, jwks):
    v = verifier(jwks)
    now = int(time.time())
    for token in (
        signer.mint(),
        signer.mint(iss=ISSUER_V1),
        signer.mint(aud=CLIENT_ID),
        signer.mint(exp=now - 30),  # inside the 60 second skew
        signer.mint(nbf=now + 30),
        signer.mint(tid=TENANT.upper(), oid=PERSON.upper()),
    ):
        principal = v.verify(token)
        assert principal.object_id == PERSON and principal.tenant_id == TENANT
        assert principal.scopes == {"access_as_user"} and principal.app_only is False
        assert principal.is_person("access_as_user") and not principal.is_person("other")


def test_a_list_audience_and_an_app_only_token_are_understood(signer, jwks):
    v = verifier(jwks)
    assert v.verify(signer.mint(aud=["elsewhere", AUDIENCE])).object_id == PERSON
    service = v.verify(signer.mint(oid=SERVICE, scp=None, roles=["Reader"], idtyp="app"))
    assert service.app_only and service.scopes == frozenset() and not service.is_person("access_as_user")
    flagged = v.verify(signer.mint(idtyp="app"))  # a scope, but the token says it is an app's: not a person
    assert flagged.app_only and not flagged.is_person("access_as_user")


def test_the_skew_is_a_setting(signer, jwks):
    now = int(time.time())
    with pytest.raises(AuthError):
        verifier(jwks, CC_ENTRA_CLOCK_SKEW_SECONDS="0").verify(signer.mint(exp=now - 5))
    assert verifier(jwks, CC_ENTRA_CLOCK_SKEW_SECONDS="300").verify(signer.mint(exp=now - 200)).object_id == PERSON


# --------------------------------------------------------------------------------------------- key cache


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_keys_are_fetched_once_and_refetched_after_the_cache_lifetime(signer, jwks):
    clock = Clock()
    v = verifier(jwks, clock, CC_ENTRA_JWKS_CACHE_SECONDS="120")
    for _ in range(5):
        v.verify(signer.mint())
    assert jwks.calls == 1
    clock.now += 119
    v.verify(signer.mint())
    assert jwks.calls == 1
    clock.now += 2
    v.verify(signer.mint())
    assert jwks.calls == 2


def test_an_unknown_kid_refetches_at_most_once_per_cooldown(signer, jwks):
    clock = Clock()
    v = verifier(jwks, clock)
    v.verify(signer.mint())
    probe = signer.mint(headers={"kid": "nope"})
    for _ in range(20):  # a flood of tokens with an invented kid must not become a flood of key downloads
        with pytest.raises(AuthError):
            v.verify(probe)
    assert jwks.calls == 1  # inside the cooldown after the first fetch: no download at all
    clock.now += entra.JWKS_REFRESH_COOLDOWN_SECONDS
    for _ in range(20):
        with pytest.raises(AuthError):
            v.verify(probe)
    assert jwks.calls == 2  # one refetch for the whole flood


def test_key_rotation_is_picked_up_on_the_next_unknown_kid(signer, jwks):
    clock = Clock()
    v = verifier(jwks, clock)
    v.verify(signer.mint())
    successor = Signer("test-key-2")
    jwks.keys = [signer.jwk, successor.jwk]
    clock.now += entra.JWKS_REFRESH_COOLDOWN_SECONDS
    assert v.verify(successor.mint()).object_id == PERSON
    jwks.keys = [successor.jwk]  # the old key is withdrawn: a refresh drops it
    clock.now += 901
    with pytest.raises(AuthError) as raised:
        v.verify(signer.mint())
    assert raised.value.failure is AuthFailure.KEY


def test_an_unreachable_key_set_is_unavailable_not_a_pass(signer, jwks):
    jwks.fail = True
    with pytest.raises(AuthError) as raised:
        verifier(jwks).verify(signer.mint())
    assert raised.value.failure is AuthFailure.UNAVAILABLE


def test_http_answers_503_when_keys_cannot_be_fetched(signer, jwks, client):
    jwks.fail = True
    response = client.get("/api/nope", headers=bearer(signer.mint()))
    assert response.status_code == 503 and response.headers["Retry-After"] == "5"
    assert response.json()["error"]["code"] == "auth_unavailable"
    assert client.get("/api/health").status_code == 200  # health never depends on the key set


def test_cached_keys_survive_a_short_outage_and_are_dropped_after_a_long_one(signer, jwks):
    clock = Clock()
    v = verifier(jwks, clock, CC_ENTRA_JWKS_CACHE_SECONDS="100")
    v.verify(signer.mint())
    jwks.fail = True
    clock.now += 150  # stale, refresh fails, the cached key still verifies
    assert v.verify(signer.mint()).object_id == PERSON
    clock.now += 400  # beyond MAX_STALE_FACTOR lifetimes: nothing left to trust
    with pytest.raises(AuthError) as raised:
        v.verify(signer.mint())
    assert raised.value.failure is AuthFailure.UNAVAILABLE


@pytest.mark.parametrize(
    "document",
    [{"keys": []}, {"keys": [{"kty": "oct", "kid": "k", "k": "AAAA"}]}, {"nonsense": True}],
)
def test_a_key_set_without_a_usable_rsa_signing_key_is_unavailable(signer, document):
    cache = JwksCache("https://keys.test/", lambda url: document, ttl=100)
    with pytest.raises(AuthError) as raised:
        cache.key_for("k")
    assert raised.value.failure is AuthFailure.UNAVAILABLE


def test_encryption_keys_in_the_set_are_not_used_to_verify(signer):
    cache = JwksCache("https://keys.test/", lambda url: {"keys": [{**signer.jwk, "use": "enc"}]}, ttl=100)
    with pytest.raises(AuthError) as raised:
        cache.key_for(KID)
    assert raised.value.failure is AuthFailure.UNAVAILABLE


# ------------------------------------------------------------------------------ the default key fetcher


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body, self.status = body, status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class FakeOpener:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.seen: dict[str, Any] = {}

    def open(self, request, timeout):
        self.seen = {"url": request.full_url, "timeout": timeout}
        return self.response


def _opener(monkeypatch, response: FakeResponse) -> FakeOpener:
    opener = FakeOpener(response)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: opener)
    return opener


def test_default_fetcher_reads_https_json_with_a_timeout(monkeypatch):
    opener = _opener(monkeypatch, FakeResponse(b'{"keys": []}'))
    assert entra.fetch_jwks_over_https("https://keys.test/k") == {"keys": []}
    assert opener.seen == {"url": "https://keys.test/k", "timeout": entra.JWKS_FETCH_TIMEOUT_SECONDS}


@pytest.mark.parametrize(
    ("url", "response"),
    [
        ("http://keys.test/k", FakeResponse(b"{}")),
        ("https://keys.test/k", FakeResponse(b"{}", status=500)),
        ("https://keys.test/k", FakeResponse(b"x" * (entra.MAX_JWKS_BYTES + 1))),
        ("https://keys.test/k", FakeResponse(b"[1, 2]")),
    ],
)
def test_default_fetcher_refuses_http_errors_oversize_and_non_objects(monkeypatch, url, response):
    _opener(monkeypatch, response)
    with pytest.raises(ValueError):  # noqa: PT011 - the message is the library's own; the type is the contract
        entra.fetch_jwks_over_https(url)


def test_default_fetcher_never_follows_a_redirect():
    handler = entra._NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://elsewhere.test/") is None


# ----------------------------------------------------------------------------------- middleware corners


def test_a_websocket_is_closed_and_lifespan_passes_through(jwks):
    sent: list[dict] = []
    reached: list[str] = []

    async def inner(scope, receive, send):
        reached.append(scope["type"])

    async def send(message):
        sent.append(message)

    middleware = EntraAuthMiddleware(inner, verifier(jwks))
    asyncio.run(middleware({"type": "websocket", "path": "/mcp", "headers": []}, None, send))
    asyncio.run(middleware({"type": "lifespan"}, None, send))
    assert sent == [{"type": "websocket.close", "code": 1008}] and reached == ["lifespan"]


# ------------------------------------------------------------------------------------- logs stay clean


def test_logs_carry_no_token_no_claim_and_no_identifier(client, signer, stranger, capsys, run_mcp):
    from cloud_crawler_appliance.security import logging as logs

    logs.configure(silent=False)
    secret_token = signer.mint(oid=OTHER_PERSON, exp=int(time.time()) - 3600, nbf=int(time.time()) - 7200)
    payload_segment = secret_token.split(".")[1]
    client.get("/api/nope", headers=bearer(secret_token))
    client.get("/api/nope", headers=bearer(stranger.mint()))
    client.get("/api/nope")
    err = capsys.readouterr().err
    lines = [json.loads(line) for line in err.splitlines() if line.strip()]
    rejections = [line for line in lines if line.get("event") == "request_error"]
    assert [r["reason"] for r in rejections] == ["expired", "signature", "missing"]
    assert all(r["status"] == 401 for r in rejections)
    for forbidden in (secret_token, payload_segment, OTHER_PERSON, PERSON, TENANT, AUDIENCE, "Bearer", KID):
        assert forbidden not in err


# --------------------------------------------------------------- tools: the actor comes from the token


@pytest.fixture
def run_mcp(serve_app) -> Callable[..., Any]:
    """`run_mcp(app, body, token)`: serve `app`, then run `body(client)` as an MCP client that sends `token`."""

    def run(app, body: Callable[..., Any], token: str):
        @asynccontextmanager
        async def connect(url: str):
            async with (
                httpx2.AsyncClient(headers=bearer(token)) as http,
                Client(streamable_http_client(f"{url}/mcp", http_client=http)) as client,
            ):
                yield client

        async def main(url: str):
            async with connect(url) as client:
                return await body(client)

        return asyncio.run(main(serve_app(app)))

    return run


async def _call(client: Client, tool: str, **args: Any) -> dict[str, Any]:
    result = await client.call_tool(tool, args)
    text = "".join(getattr(c, "text", "") for c in result.content)
    # the SDK prefixes a tool's refusal with "Error executing tool <name>: "; the tool's own code follows
    return {"error": text.partition(": ")[2]} if result.is_error else result.structured_content


async def _decision(client: Client, decision: dict, **extra: Any) -> str:
    created = await _call(client, "adr_create", decision={**decision, **extra})
    return created["decisionId"]


def test_the_accepting_person_is_the_token_not_the_typed_actor(app, signer, wave_one_decision, run_mcp):
    async def body(client):
        decision_id = await _decision(client, wave_one_decision)
        # the typed actorId names somebody else: refused, and the decision stays unaccepted
        spoof = await _call(client, "adr_accept", decisionId=decision_id, actorId=OTHER_PERSON)
        assert spoof["error"].startswith("forbidden") and OTHER_PERSON not in spoof["error"]
        assert (await _call(client, "adr_get", decisionId=decision_id))["status"] != "accepted"
        # no typed actorId: the token's object id is recorded, as a hash
        accepted = await _call(client, "adr_accept", decisionId=decision_id)
        assert accepted["acceptedBy"] == sha256_text(PERSON) and PERSON not in json.dumps(accepted)
        return decision_id

    run_mcp(app, body, signer.mint())


def test_a_matching_typed_actor_is_accepted_in_any_letter_case(app, signer, wave_one_decision, run_mcp):
    async def body(client):
        decision_id = await _decision(client, wave_one_decision)
        accepted = await _call(client, "adr_accept", decisionId=decision_id, actorId=f"  {PERSON.upper()} ")
        assert accepted["acceptedBy"] == sha256_text(PERSON)

    run_mcp(app, body, signer.mint())


def test_review_decide_records_the_token_identity_and_refuses_a_spoof(app, signer, run_mcp):
    async def body(client):
        proposed = await _call(client, "review_propose", proposal={"kind": "advisor", "title": "t", "rationale": "r"})
        pid = proposed["proposalId"]
        spoof = await _call(client, "review_decide", proposalId=pid, decision="approve", actorId=OTHER_PERSON)
        assert spoof["error"].startswith("forbidden")
        decided = await _call(client, "review_decide", proposalId=pid, decision="approve")
        assert decided["approval"]["actorId"] == sha256_text(PERSON) and decided["status"] == "approved"

    run_mcp(app, body, signer.mint())


def test_adr_create_records_the_token_as_author_and_refuses_a_conflicting_author(
    app, signer, wave_one_decision, run_mcp
):
    async def body(client):
        wrong = await _call(client, "adr_create", decision={**wave_one_decision, "actorId": OTHER_PERSON})
        assert wrong["error"].startswith("forbidden")
        decision_id = await _decision(client, wave_one_decision)
        assert (await _call(client, "adr_get", decisionId=decision_id))["createdBy"] == sha256_text(PERSON)

    run_mcp(app, body, signer.mint())


@pytest.mark.parametrize(
    "claims",
    [
        {"oid": SERVICE, "scp": None, "roles": ["Reader"], "idtyp": "app"},  # a service (client credentials)
        {"scp": "other_scope"},  # a delegated token without the human scope
        {"idtyp": "app"},  # an app token that happens to carry the scope text
    ],
    ids=["app-only", "wrong-scope", "idtyp-app"],
)
def test_services_and_agents_cannot_act_as_a_person(app, signer, wave_one_decision, claims, run_mcp):
    async def body(client):
        decision_id = await _decision(client, wave_one_decision)  # model-class tools are open to any valid caller
        assert (await _call(client, "adr_list"))["total"] == 1
        for tool, args in (
            ("adr_accept", {"decisionId": decision_id}),
            ("adr_accept", {"decisionId": decision_id, "actorId": claims.get("oid", PERSON)}),
            ("review_decide", {"proposalId": "prp_x", "decision": "approve"}),
        ):
            refused = await _call(client, tool, **args)
            assert refused["error"].startswith("forbidden: this tool needs a signed-in person")

    run_mcp(app, body, signer.mint(**claims))


def test_the_human_scope_is_a_setting(jwks, wave_one_decision, signer, run_mcp):
    env = {**ENTRA_ENV, "CC_ENTRA_HUMAN_SCOPE": "decisions.approve"}

    def fresh():  # the streamable HTTP session manager of one app instance runs only once
        return create_app(Settings.from_env(env), env=env, jwks_fetcher=jwks)

    async def body(client):
        decision_id = await _decision(client, wave_one_decision)
        return await _call(client, "adr_accept", decisionId=decision_id)

    assert run_mcp(fresh(), body, signer.mint(scp="access_as_user"))["error"].startswith("forbidden")
    assert "acceptedBy" in run_mcp(fresh(), body, signer.mint(scp="decisions.approve other"))


def test_a_tool_called_without_a_request_is_refused_when_sign_in_is_required(wave_one_decision):
    """Defence in depth: the server built for Entra never falls back to the caller's word, even in-process."""
    from cloud_crawler_core.ledger import InMemoryLedger

    from cloud_crawler_appliance.mcp_server import AuthPolicy, build_mcp_server

    async def main():
        async with Client(build_mcp_server(InMemoryLedger(), auth=AuthPolicy(required=True))) as client:
            created = await _call(client, "adr_create", decision=wave_one_decision)
            accepted = await _call(client, "adr_accept", decisionId="dec_x", actorId=PERSON)
            return created, accepted

    created, accepted = asyncio.run(main())
    assert created["error"].startswith("unauthenticated") and accepted["error"].startswith("unauthenticated")


def test_with_sign_in_off_the_typed_actor_still_works_as_before(quiet_env, wave_one_decision, serve_app):
    app = create_app(Settings.from_env(quiet_env), env=quiet_env)

    async def body(client):
        decision_id = await _decision(client, wave_one_decision, actorId=PERSON)
        assert "actorId is required" in (await _call(client, "adr_accept", decisionId=decision_id))["error"]
        accepted = await _call(client, "adr_accept", decisionId=decision_id, actorId=OTHER_PERSON)
        assert accepted["acceptedBy"] == sha256_text(OTHER_PERSON)

    async def main(url: str):
        async with Client(f"{url}/mcp") as client:
            await body(client)

    asyncio.run(main(serve_app(app)))


def test_tool_metadata_is_unchanged_by_sign_in(app, signer, run_mcp):
    async def body(client):
        tools = (await client.list_tools()).tools
        assert {t.name for t in tools if t.meta["caller"] == "human"} == {"adr_accept", "review_decide"}
        assert all(t.meta["callsAzure"] is False for t in tools)
        accept = next(t for t in tools if t.name == "adr_accept")
        assert accept.input_schema["required"] == ["decisionId"]  # actorId is optional when the token supplies it

    run_mcp(app, body, signer.mint())
