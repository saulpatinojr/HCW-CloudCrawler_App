from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cloud_crawler_appliance import ADDON_ID, __version__
from cloud_crawler_appliance.api import create_app
from cloud_crawler_appliance.config import Settings
from cloud_crawler_appliance.edition import EditionError


@pytest.fixture
def client(quiet_env):
    with TestClient(create_app(Settings.from_env(quiet_env), env=quiet_env)) as c:
        yield c


def test_health_is_flat(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True and body["id"] == ADDON_ID and body["version"] == __version__
    assert body["edition"] == "appliance" and body["azureConnectivity"] == "not-configured"
    assert body["production"] is False and body["asOf"].endswith("Z")
    assert body["engine"]["detectors"] == ["zone-redundancy"]
    assert body["mcp"] == {"path": "/mcp", "protocolVersion": "2026-07-28", "stateless": True}
    assert body["ledger"] == {"decisions": 0, "evidence": 0, "openContradictions": 0, "openProposals": 0}
    assert body["limits"]["maxRows"] == 5000


def test_api_headers(client):
    response = client.get("/api/health")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_unknown_api_routes_use_the_envelope(client):
    assert client.get("/api/nope").json() == {"error": {"code": "not_found", "message": "no such route"}}
    assert client.post("/api/health").json()["error"]["code"] == "method_not_allowed"
    assert client.get("/api/nope").status_code == 404 and client.post("/api/health").status_code == 405


def test_docs_are_disabled(client):
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


def test_mcp_endpoint_is_mounted(client):
    # A POST that is not JSON-RPC is refused by the transport (4xx), not routed to the 404 envelope. A plain GET is
    # never sent here: on a streamable HTTP endpoint it opens an event stream, which a synchronous client would wait on.
    response = client.post(
        "/mcp",
        content="not json-rpc",
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
    )
    assert 400 <= response.status_code < 500
    assert "no such route" not in response.text


def test_create_app_refuses_secret_bearing_env():
    with pytest.raises(EditionError):
        create_app(Settings(), env={"AZURE_CLIENT_SECRET": "x"})
