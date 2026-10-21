from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from cloud_crawler_appliance.api import create_app
from cloud_crawler_appliance.config import Settings

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
RECORDINGS = SAMPLES / "azure-mcp"


@pytest.fixture
def sample_export() -> dict:
    return json.loads((SAMPLES / "sample-resource-graph.json").read_text(encoding="utf-8"))


@pytest.fixture
def sample_decision() -> dict:
    return json.loads((SAMPLES / "decision-zone-redundancy.json").read_text(encoding="utf-8"))


@pytest.fixture
def wave_one_decision() -> dict:
    return json.loads((SAMPLES / "decision-wave-one.json").read_text(encoding="utf-8"))


@pytest.fixture
def observations_decision() -> dict:
    return json.loads((SAMPLES / "decision-azure-observations.json").read_text(encoding="utf-8"))


@pytest.fixture
def quiet_env() -> dict[str, str]:
    return {"CC_LOG_SILENT": "1", "CC_ALLOWED_HOSTS": "testserver 127.0.0.1:* localhost:*"}


def serve(app):
    """Run `app` under uvicorn on a free loopback port for the duration of a test; yields the base URL."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
    sock.close()


@pytest.fixture
def http_server(quiet_env):
    yield from serve(create_app(Settings.from_env(quiet_env), env=quiet_env))


@pytest.fixture
def recordings_dir() -> Path:
    return RECORDINGS


@pytest.fixture
def recorded_http_server(quiet_env):
    """The appliance with the recorded Azure MCP host, so `collection_run_azure` exists."""
    env = {**quiet_env, "CC_AZMCP_MODE": "recorded", "CC_AZMCP_RECORDINGS": str(RECORDINGS)}
    yield from serve(create_app(Settings.from_env(env), env=env))
