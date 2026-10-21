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
def quiet_env() -> dict[str, str]:
    return {"CC_LOG_SILENT": "1", "CC_ALLOWED_HOSTS": "testserver 127.0.0.1:* localhost:*"}


@pytest.fixture
def http_server(quiet_env):
    app = create_app(Settings.from_env(quiet_env), env=quiet_env)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
