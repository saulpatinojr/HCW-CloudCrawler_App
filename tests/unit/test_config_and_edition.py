from __future__ import annotations

import pytest

from cloud_crawler_appliance.config import MAX_SETTING, Settings
from cloud_crawler_appliance.edition import (
    AZURE_CONNECTIVITY,
    CAPABILITIES,
    EDITION,
    FORBIDDEN_ENV,
    EditionError,
    assert_appliance_ready,
    refuse_forbidden_env,
)


def test_settings_defaults_and_env():
    assert Settings.from_env({}) == Settings()
    s = Settings.from_env({"PORT": "9000", "CC_LOG_SILENT": "yes", "CC_MAX_ROWS": "10", "CC_EVIDENCE_TTL_HOURS": "2"})
    assert (s.port, s.log_silent, s.max_rows, s.evidence_ttl_hours) == (9000, True, 10, 2)
    assert Settings.from_env({"CC_ALLOWED_HOSTS": "Crawler.example.test, crawler.example.test:8080"}).allowed_hosts == (
        "crawler.example.test",
        "crawler.example.test:8080",
    )
    with pytest.raises(ValueError):
        Settings.from_env({"CC_ALLOWED_HOSTS": "https://crawler.example.test/"})


@pytest.mark.parametrize("value", ["0", "-1", "abc", str(MAX_SETTING + 1), "1" * 11])
def test_settings_reject_bad_numbers(value):
    with pytest.raises(ValueError):
        Settings.from_env({"PORT": value})


def test_edition_constants():
    assert EDITION == "appliance" and AZURE_CONNECTIVITY == "not-configured" and "mcp" in CAPABILITIES


@pytest.mark.parametrize("name", FORBIDDEN_ENV)
def test_secret_bearing_variables_are_refused(name):
    with pytest.raises(EditionError) as exc:
        refuse_forbidden_env({name: "value"})
    assert name in str(exc.value) and "value" not in str(exc.value)


def test_empty_forbidden_variable_is_ignored_and_clean_env_passes():
    refuse_forbidden_env({"AZURE_CLIENT_SECRET": ""})
    assert_appliance_ready({"AZURE_CLIENT_ID": "00000000-0000-0000-0000-000000000009"})
