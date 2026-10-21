"""A fresh process refuses to start, with exit code 3 and a scrubbed reason, when a secret-bearing variable is set."""

from __future__ import annotations

import json
import os
import subprocess
import sys


def test_process_exits_3_under_client_secret():
    env = {k: v for k, v in os.environ.items() if not k.startswith("AZURE_")}
    env["AZURE_CLIENT_SECRET"] = "not-a-real-secret-00000000"
    env["CC_LOG_SILENT"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "cloud_crawler_appliance"], env=env, capture_output=True, text=True, timeout=60
    )
    assert completed.returncode == 3
    line = json.loads(completed.stderr.strip().splitlines()[-1])
    assert line["event"] == "startup_refused" and "AZURE_CLIENT_SECRET" in line["reason"]
    assert "not-a-real-secret" not in completed.stderr
