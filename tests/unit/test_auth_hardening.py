"""The two guards added by the ADR 0004 amendment of 2026-10-26: no unauthenticated start on a non-loopback address
without a loudly named opt-out, and an optional app-role check. No network and no real tenant: the key is generated
when the tests start and every token is minted here.
"""

# The fixtures (signer, jwks, run_mcp) are imported from the sign-in tests, which is how pytest shares them between
# modules without a package; a test then names the fixture as a parameter, which ruff reads as a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Reuse the signer, the key set double and the helpers of the sign-in tests; nothing is duplicated.
from test_entra_auth import (  # noqa: F401 - fixtures are collected by name
    ENTRA_ENV,
    PERSON,
    SERVICE,
    TENANT,
    FakeJwks,
    Signer,
    _call,
    bearer,
    jwks,
    run_mcp,
    signer,
)

from cloud_crawler_appliance import __main__ as entry
from cloud_crawler_appliance.api import create_app
from cloud_crawler_appliance.config import Settings
from cloud_crawler_appliance.security.entra import AuthError, AuthFailure, TokenVerifier

OPEN = "CC_ALLOW_UNAUTHENTICATED_NON_LOOPBACK"
ROLE = "CloudCrawler.Access"
OTHER_ROLE = "CloudCrawler.Admin"
ROLE_ENV = {**ENTRA_ENV, "CC_AUTH_REQUIRED_ROLES": ROLE}
ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------ refuse unauthenticated on a non-loopback bind


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.10", "::", "2001:db8::1"])  # noqa: S104
def test_sign_in_off_on_a_non_loopback_address_is_refused(host):
    with pytest.raises(ValueError, match=OPEN) as raised:
        Settings.from_env({"CC_BIND_HOST": host})
    assert "CC_AUTH_MODE=entra" in str(raised.value)  # the message names the way out, not only the refusal
    with pytest.raises(ValueError, match=OPEN):
        Settings(bind_host=host)  # the constructor enforces it too, not only the environment reader


@pytest.mark.parametrize("host", ["", "127.0.0.1", "127.0.0.2", "::1"])
def test_sign_in_off_on_loopback_still_starts_with_no_opt_out(host):
    settings = Settings.from_env({"CC_BIND_HOST": host})
    assert settings.auth_mode == "off" and settings.allow_unauthenticated_non_loopback is False


def test_the_opt_out_lets_the_lab_start_on_all_interfaces():
    settings = Settings.from_env({"CC_BIND_HOST": "0.0.0.0", OPEN: "true"})  # noqa: S104
    assert settings.allow_unauthenticated_non_loopback is True and settings.auth_mode == "off"


@pytest.mark.parametrize("value", ["", "false", "0", "no", "off", "maybe", "tru", "TRUEISH"])
def test_anything_but_a_clear_yes_is_not_an_opt_out(value):
    with pytest.raises(ValueError, match=OPEN):
        Settings.from_env({"CC_BIND_HOST": "0.0.0.0", OPEN: value})  # noqa: S104


def test_sign_in_on_needs_no_opt_out_on_any_address():
    settings = Settings.from_env({**ENTRA_ENV, "CC_BIND_HOST": "0.0.0.0"})  # noqa: S104
    assert settings.auth_mode == "entra"


def test_the_opt_out_beside_sign_in_is_refused_so_it_cannot_survive_a_later_switch():
    with pytest.raises(ValueError, match=f"{OPEN} is only for CC_AUTH_MODE=off"):
        Settings.from_env({**ENTRA_ENV, OPEN: "true"})
    assert Settings.from_env({**ENTRA_ENV, OPEN: "false"}).auth_mode == "entra"  # an explicit no is harmless


def test_the_default_settings_are_unchanged_and_loopback():
    settings = Settings.from_env({})
    assert settings == Settings() and settings.bind_host == "127.0.0.1" and settings.auth_required_roles == ()


def test_main_exits_3_and_names_the_setting_when_unauthenticated_on_all_interfaces(monkeypatch, capsys):
    import os

    for name in list(os.environ):
        if name.startswith(("AZURE_", "CC_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("CC_LOG_SILENT", "1")
    monkeypatch.setenv("CC_BIND_HOST", "0.0.0.0")  # noqa: S104 - what the container image sets
    started = []
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
    assert entry.main() == 3
    line = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert line["event"] == "startup_refused" and OPEN in line["reason"] and not started  # the server never listened


def test_a_fresh_process_refuses_the_image_default_without_sign_in_or_opt_out():
    """The container image sets CC_BIND_HOST=0.0.0.0 and nothing else: this is what `docker run` does with no flags."""
    import os

    env = {k: v for k, v in os.environ.items() if not k.startswith(("AZURE_", "CC_"))}
    env.update({"CC_BIND_HOST": "0.0.0.0", "CC_LOG_SILENT": "1", "PORT": "8080"})  # noqa: S104
    completed = subprocess.run(  # noqa: S603 - the interpreter running these tests
        [sys.executable, "-m", "cloud_crawler_appliance"], env=env, capture_output=True, text=True, timeout=60
    )
    assert completed.returncode == 3
    assert OPEN in json.loads(completed.stderr.strip().splitlines()[-1])["reason"]


def test_the_image_binds_all_interfaces_but_does_not_carry_the_opt_out():
    """Design: the image never ships the opt-out, so `docker run` without sign-in or an explicit `-e` is refused."""
    dockerfile = (ROOT / "infrastructure/docker/Dockerfile").read_text(encoding="utf-8")
    env_lines = [line for line in dockerfile.splitlines() if line.lstrip().startswith("ENV ")]
    assert any("CC_BIND_HOST=0.0.0.0" in line for line in env_lines)
    assert not any(OPEN in line for line in env_lines)
    assert not any("CC_AUTH_MODE" in line for line in env_lines)  # the operator chooses; nothing is pre-decided


def test_no_workflow_or_script_sets_the_opt_out_except_the_lab_image_smoke_test():
    """The opt-out may appear in CI only on the one `docker run` that proves the image answers health."""
    users = []
    for path in [*(ROOT / ".github").rglob("*.yml"), *(ROOT / "scripts").iterdir(), ROOT / "Makefile"]:
        if path.is_file() and OPEN in path.read_text(encoding="utf-8", errors="replace"):
            users.append(path.relative_to(ROOT).as_posix())
    assert users == [".github/workflows/ci.yml"]


# ------------------------------------------------------------------------------------------- the role setting


def test_roles_are_read_cleaned_and_bounded():
    assert Settings.from_env(ENTRA_ENV).auth_required_roles == ()  # default: no role check
    assert Settings.from_env({**ENTRA_ENV, "CC_AUTH_REQUIRED_ROLES": ""}).auth_required_roles == ()
    got = Settings.from_env({**ENTRA_ENV, "CC_AUTH_REQUIRED_ROLES": f" {ROLE}, {OTHER_ROLE} {ROLE} "})
    assert got.auth_required_roles == (ROLE, OTHER_ROLE)  # comma or space, whitespace trimmed, duplicates dropped
    for bad in ("x" * 129, "bad\x7frole", " ".join(f"role{i}" for i in range(33))):
        with pytest.raises(ValueError, match="CC_AUTH_REQUIRED_ROLES"):
            Settings.from_env({**ENTRA_ENV, "CC_AUTH_REQUIRED_ROLES": bad})


def test_roles_with_sign_in_off_are_refused_not_ignored():
    with pytest.raises(ValueError, match="CC_AUTH_REQUIRED_ROLES"):
        Settings.from_env({"CC_AUTH_REQUIRED_ROLES": ROLE})
    with pytest.raises(ValueError, match="needs CC_AUTH_MODE=entra"):
        Settings(auth_required_roles=(ROLE,))


def test_an_empty_role_list_is_todays_behaviour(signer, jwks):
    app = create_app(Settings.from_env(ENTRA_ENV), env=ENTRA_ENV, jwks_fetcher=jwks)
    with TestClient(app) as c:
        # no `roles` claim at all, and a role claim of the wrong shape: both still pass when no role is required
        assert c.get("/api/nope", headers=bearer(signer.mint())).status_code == 404
        assert c.get("/api/nope", headers=bearer(signer.mint(roles="not-a-list"))).status_code == 404


@pytest.fixture
def role_client(jwks):
    with TestClient(create_app(Settings.from_env(ROLE_ENV), env=ROLE_ENV, jwks_fetcher=jwks)) as c:
        yield c


def test_a_token_with_the_required_role_passes(role_client, signer):
    assert (
        role_client.get("/api/nope", headers=bearer(signer.mint(roles=[ROLE]))).status_code == 404
    )  # reached the router
    assert role_client.get("/api/nope", headers=bearer(signer.mint(roles=["Other", ROLE]))).status_code == 404


def test_any_one_of_several_required_roles_is_enough(jwks, signer):
    env = {**ENTRA_ENV, "CC_AUTH_REQUIRED_ROLES": f"{ROLE},{OTHER_ROLE}"}
    with TestClient(create_app(Settings.from_env(env), env=env, jwks_fetcher=jwks)) as c:
        assert c.get("/api/nope", headers=bearer(signer.mint(roles=[OTHER_ROLE]))).status_code == 404
        assert c.get("/api/nope", headers=bearer(signer.mint(roles=["Unrelated"]))).status_code == 403


@pytest.mark.parametrize(
    "claims",
    [
        {},  # no `roles` claim (a user who was never assigned the role)
        {"roles": []},
        {"roles": ["Unrelated"]},
        {"roles": [ROLE.lower()]},  # roles are compared exactly, as Entra emits them
        {"roles": f"{ROLE}"},  # a string, not a list: never read as a role
        {"roles": [ROLE, 7]},  # a list with a non-text member is not trusted at all
        {"roles": {ROLE: True}},
        {"scp": ROLE},  # the role name as a *scope* is not a role
        {"scp": None, "idtyp": "app", "oid": SERVICE},  # an app-only token without the role
    ],
    ids=["absent", "empty", "other", "case", "string", "mixed", "object", "scope-not-role", "app-without-role"],
)
def test_a_token_without_the_required_role_gets_403_with_a_generic_body(role_client, signer, claims):
    response = role_client.get("/api/nope", headers=bearer(signer.mint(**claims)))
    assert response.status_code == 403
    assert response.json() == {
        "error": {"code": "forbidden", "message": "this identity is not allowed to use the service"}
    }
    assert ROLE not in response.text and "role" not in response.text.lower()  # does not say what would be enough
    assert "WWW-Authenticate" not in response.headers  # signing in again would not help
    assert response.headers["Cache-Control"] == "no-store" and response.headers["X-Content-Type-Options"] == "nosniff"


def test_the_role_check_covers_mcp_and_leaves_health_and_the_401s_alone(role_client, signer):
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    accept = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    no_role = bearer(signer.mint())
    assert role_client.post("/mcp", json=rpc, headers={**accept, **no_role}).status_code == 403
    assert role_client.post("/mcp", json=rpc, headers=accept).status_code == 401  # no token is still 401
    assert role_client.get("/api/nope", headers=bearer("not-a-token")).status_code == 401  # a bad token is still 401
    forged = role_client.get("/api/nope", headers=bearer(signer.mint(aud="api://elsewhere", roles=[ROLE])))
    assert forged.status_code == 401  # the role of an invalid token is never looked at
    health = role_client.get("/api/health")
    assert health.status_code == 200 and health.json()["auth"] == "entra"
    allowed = role_client.post("/mcp", json=rpc, headers={**accept, **bearer(signer.mint(roles=[ROLE]))})
    assert allowed.status_code not in (401, 403)


def test_the_denial_is_logged_as_a_status_and_a_fixed_word_only(role_client, signer, capsys):
    from cloud_crawler_appliance.security import logging as logs

    logs.configure(silent=False)
    token = signer.mint(roles=[OTHER_ROLE], oid=SERVICE)
    role_client.get("/api/nope", headers=bearer(token))
    err = capsys.readouterr().err
    event = next(json.loads(line) for line in err.splitlines() if '"request_error"' in line)
    assert event["status"] == 403 and event["reason"] == "role"
    for forbidden in (token, SERVICE, TENANT, ROLE, OTHER_ROLE):
        assert forbidden not in err


def test_the_verifier_names_the_reason(signer, jwks):
    v = TokenVerifier(Settings.from_env(ROLE_ENV), jwks)
    principal = v.verify(signer.mint(roles=[ROLE]))
    assert principal.roles == {ROLE}
    v.authorize(principal)
    with pytest.raises(AuthError) as raised:
        v.authorize(v.verify(signer.mint()))
    assert raised.value.failure is AuthFailure.ROLE


# ---------------------------------------- roles and delegated scopes together: ADR 0004 item 5 still holds


def test_a_signed_in_person_with_the_role_can_still_act_and_a_service_with_the_role_still_cannot(
    jwks, signer, wave_one_decision, run_mcp
):
    def fresh():  # the streamable HTTP session manager of one app instance runs only once
        return create_app(Settings.from_env(ROLE_ENV), env=ROLE_ENV, jwks_fetcher=jwks)

    async def person(client):
        created = await _call(client, "adr_create", decision=wave_one_decision)
        accepted = await _call(client, "adr_accept", decisionId=created["decisionId"])
        assert accepted["status"] == "accepted"  # scope access_as_user + the role: the human-only tool works

    run_mcp(fresh(), person, signer.mint(roles=[ROLE]))

    async def service(client):
        created = await _call(client, "adr_create", decision=wave_one_decision)  # model-class tools: allowed
        assert created["decisionId"]
        refused = await _call(client, "adr_accept", decisionId=created["decisionId"])
        assert refused["error"].startswith("forbidden: this tool needs a signed-in person")  # app-only: still refused

    run_mcp(fresh(), service, signer.mint(oid=SERVICE, scp=None, idtyp="app", roles=[ROLE]))


def test_a_person_without_the_role_is_stopped_before_any_tool_runs(jwks, signer, run_mcp):
    app = create_app(Settings.from_env(ROLE_ENV), env=ROLE_ENV, jwks_fetcher=jwks)

    async def body(client):
        return await _call(client, "adr_list")

    with pytest.raises(Exception):  # noqa: B017, PT011 - the transport reports the 403 as a connection error
        run_mcp(app, body, signer.mint())  # delegated and in scope, but no role


# --------------------------------------------------------------------------- the settings file and the docs


def test_every_new_setting_is_listed_in_env_example_and_the_readme_and_the_adr():
    for name in (OPEN, "CC_AUTH_REQUIRED_ROLES"):
        for path in (".env.example", "README.md", "docs/adr/0004-entra-token-validation-on-api-and-mcp.md"):
            assert name in (ROOT / path).read_text(encoding="utf-8"), f"{name} is missing from {path}"
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(rf"^{OPEN}=\s*$", example, re.MULTILINE)  # never shipped as true
