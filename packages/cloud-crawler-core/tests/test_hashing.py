from __future__ import annotations

import pytest
from cloud_crawler_core.hashing import canonical_json, sha256_of, sha256_text
from cloud_crawler_core.models import Correlation


def test_canonical_json_is_key_order_independent():
    assert canonical_json({"b": 1, "a": [1, {"d": 2, "c": 3}]}) == canonical_json({"a": [1, {"c": 3, "d": 2}], "b": 1})


def test_canonical_json_has_no_whitespace_and_keeps_unicode():
    assert canonical_json({"k": "é"}) == '{"k":"é"}'.encode()


def test_canonical_json_rejects_nan():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_sha256_of_models_and_dicts_agree():
    model = Correlation(type="resource", value="/x")
    assert sha256_of(model) == sha256_of({"type": "resource", "value": "/x"})
    assert sha256_of(model).startswith("sha256:") and len(sha256_of(model)) == 7 + 64


def test_sha256_text_is_stable():
    assert sha256_text("abc") == "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
