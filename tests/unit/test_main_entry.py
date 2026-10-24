"""`python -m cloud_crawler_appliance`, run in this process so coverage sees it: the startup refusals, the scrubbed
reason, the uvicorn settings, and the `__main__` guard. (`tests/security/test_startup_refusal.py` covers the same
refusal in a fresh process, which coverage cannot measure.)"""

from __future__ import annotations

import json
import runpy

import pytest

from cloud_crawler_appliance import __main__ as entry
from cloud_crawler_appliance.edition import FORBIDDEN_ENV


@pytest.fixture
def clean_env(monkeypatch):
    for name in list(__import__("os").environ):
        if name.startswith(("AZURE_", "CC_")) or name == "PORT":
            monkeypatch.delenv(name)
    monkeypatch.setenv("CC_LOG_SILENT", "1")
    return monkeypatch


@pytest.mark.parametrize("name", FORBIDDEN_ENV)
def test_main_refuses_each_secret_bearing_variable_with_exit_code_3(clean_env, capsys, name):
    clean_env.setenv(name, "not-a-real-secret-00000000")
    assert entry.main() == 3
    err = capsys.readouterr().err
    line = json.loads(err.strip().splitlines()[-1])
    assert line["event"] == "startup_refused" and name in line["reason"]
    assert "not-a-real-secret" not in err


def test_main_refuses_a_bad_setting_and_scrubs_the_reason(clean_env, capsys):
    clean_env.setenv("PORT", "not-a-number")
    assert entry.main() == 3
    line = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert line["event"] == "startup_refused" and line["reason"].startswith("ValueError:")


def test_main_starts_uvicorn_on_all_interfaces_without_access_log_or_proxy_headers(clean_env, monkeypatch):
    import uvicorn

    clean_env.setenv("PORT", "8123")
    seen: dict = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: seen.update(app=app, **kwargs))
    assert entry.main() == 0
    assert seen["host"] == "0.0.0.0" and seen["port"] == 8123  # noqa: S104
    assert seen["access_log"] is False and seen["proxy_headers"] is False and seen["server_header"] is False
    assert seen["log_level"] == "warning" and callable(seen["app"])


def test_module_guard_exits_with_the_code_main_returns(clean_env):
    clean_env.setenv("AZURE_CLIENT_SECRET", "not-a-real-secret-00000000")
    with pytest.raises(SystemExit) as raised:
        runpy.run_path(entry.__file__, run_name="__main__")
    assert raised.value.code == 3
