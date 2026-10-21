from __future__ import annotations

import pytest
from cloud_crawler_core.redaction import (
    REDACTED,
    VisitorDataError,
    assert_no_visitor_data,
    redact_payload,
    scrub,
)


def test_redact_payload_replaces_denied_keys_and_counts():
    payload = {
        "name": "hcw-sample-st-01",
        "properties": {
            "primaryKey": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "connectionString": "Endpoint=sb://x/;SharedAccessKey=abcdefghijklmnopqrstuvwxyz0123456789",
            "keyVaultKeyUri": "https://hcw-sample-kv.vault.azure.net/keys/k1",
            "keySource": "Microsoft.Keyvault",
        },
        "tags": {"owner": "x", "access-token": "t"},
    }
    out, count = redact_payload(payload)
    assert out["properties"]["primaryKey"] == REDACTED
    assert out["properties"]["connectionString"] == REDACTED
    assert out["properties"]["keyVaultKeyUri"].startswith("https://")  # evidence of CMK stays
    assert out["properties"]["keySource"] == "Microsoft.Keyvault"
    assert out["tags"]["access-token"] == REDACTED
    assert count == 3
    assert payload["properties"]["primaryKey"] != REDACTED  # input untouched


def test_redact_payload_replaces_secret_shaped_values_in_free_text():
    # Built at runtime so no token-shaped literal sits in the source for a secret scanner to flag; it only has to
    # match the engine's own "eyJ<segment>.<segment>" rule, not decode as a real token.
    jwt = "eyJ" + "a" * 20 + "." + "b" * 20 + "." + "c" * 16
    out, count = redact_payload({"description": f"token {jwt} leaked", "list": ["sig=" + "A" * 30]})
    assert jwt not in out["description"] and REDACTED in out["description"]
    assert out["list"] == [REDACTED]
    assert count == 2


def test_redact_payload_passes_scalars_and_empty():
    assert redact_payload(42) == (42, 0)
    assert redact_payload([]) == ([], 0)


def test_scrub_removes_guids_paths_and_secrets():
    text = (
        "sub /subscriptions/00000000-0000-0000-0000-000000000001/rg x AccountKey="
        + "B" * 40
        + " id 00000000-0000-0000-0000-000000000042"
    )
    out = scrub(text)
    assert "0000000" not in out and "AccountKey=" not in out and "000042" not in out
    assert len(scrub("x" * 2000)) == 500


def test_assert_no_visitor_data_accepts_counts_flags_and_words():
    assert_no_visitor_data({"event": "startup", "count": 3, "ok": True, "ratio": 0.5, "none": None})


@pytest.mark.parametrize("event", [{"event": "hcw-sample-sql-01"}, {"bad key": 1}, {"path": "/subscriptions/x"}])
def test_assert_no_visitor_data_rejects_text(event):
    with pytest.raises(VisitorDataError):
        assert_no_visitor_data(event)
