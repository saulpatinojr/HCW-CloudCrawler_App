"""Two redactions with two purposes.

`redact_payload` runs at ingestion over everything a caller hands in (an export, a tool result, an artifact): values
under secret-shaped keys and secret-shaped values are replaced before the payload is stored or shown. The raw
payload's hash is taken before this runs, so provenance still proves what arrived.

`scrub` and `assert_no_visitor_data` guard the log path: a log event may carry counts, durations, flags and allowed
words only, and exception text is scrubbed of GUIDs, subscription paths and secret-shaped strings.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

REDACTED = "<redacted>"

_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_SUBSCRIPTION_PATH = re.compile(r"/subscriptions/[^\s\"']*", re.IGNORECASE)
_SECRET_SHAPED = re.compile(
    r"(AccountKey=[A-Za-z0-9+/=]{20,}"
    r"|SharedAccessKey=[A-Za-z0-9+/=]{20,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r"|sig=[A-Za-z0-9%+/=]{20,}"
    r"|ghp_[A-Za-z0-9]{20,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
# Key names whose values are never evidence. `keyVaultKeyUri` and `keySource` are evidence (customer-managed keys),
# which is why the match is on the whole normalised key, not on the substring "key".
_DENIED_KEYS = re.compile(
    r"^(password|pwd|secret|clientsecret|accesskey|accountkey|primarykey|secondarykey|sharedaccesskey"
    r"|connectionstring|connectionstrings|sastoken|sasuri|token|accesstoken|refreshtoken|apikey|authorization)$"
)

ALLOWED_WORDS: frozenset[str] = frozenset(
    {
        # event names
        "startup",
        "startup_refused",
        "shutdown",
        "evidence_ingested",
        "evidence_rejected",
        "decision_created",
        "drift_evaluated",
        "proposal_created",
        "request_error",
        "unhandled_error",
        "rate_limited",
        "overloaded",
        "sweep",
        # editions, modes, kinds, states, codes
        "appliance",
        "lab",
        "obo",
        "managed-identity",
        "none",
        "not-configured",
        "disabled-by-design",
        "azure-mcp-result",
        "arg-export",
        "azqr-report",
        "tf-state",
        "tf-plan",
        "aztfexport-mapping",
        "cost-export",
        "waf-guide",
        "cloud-architect-state",
        "custom",
        "declared",
        "observed",
        "imported",
        "derived",
        "inferred",
        "proposed",
        "supported",
        "contradicted",
        "unknown",
        "not-applicable",
        "ok",
        "error",
        "invalid_json",
        "invalid_request",
        "too_large",
        "too_many_rows",
        "unsupported_kind",
        "ingestion_failed",
        "not_found",
        "method_not_allowed",
        "internal_error",
        "forbidden",
        "warning",
        "true",
        "false",
    }
)


class VisitorDataError(ValueError):
    """Raised when a log event would carry anything other than counts, durations and known words."""


def scrub(text: str) -> str:
    """Replace secret-shaped strings, subscription paths and GUIDs in free text; cap the length."""
    text = _SECRET_SHAPED.sub(REDACTED, text)
    text = _SUBSCRIPTION_PATH.sub(REDACTED, text)
    text = _GUID.sub(REDACTED, text)
    return text[:500]


def assert_no_visitor_data(event: dict[str, Any]) -> None:
    """The single guard before the log writer: every value is numeric, boolean, None, an Enum, or an allowed word."""
    for key, value in event.items():
        if not isinstance(key, str) or not key.isidentifier():
            raise VisitorDataError("log keys must be identifiers")
        if value is None or isinstance(value, bool | int | float | Enum):
            continue
        if isinstance(value, str) and value in ALLOWED_WORDS:
            continue
        raise VisitorDataError(f"log field {key!r} is not a count, flag or allowed word")


def _normalise_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def redact_payload(value: Any) -> tuple[Any, int]:
    """Return a copy of `value` with denied keys and secret-shaped strings replaced, and the number of replacements."""
    count = 0

    def walk(node: Any) -> Any:
        nonlocal count
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            for key, item in node.items():
                if isinstance(key, str) and _DENIED_KEYS.match(_normalise_key(key)):
                    out[key] = REDACTED
                    count += 1
                else:
                    out[key] = walk(item)
            return out
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, str) and _SECRET_SHAPED.search(node):
            count += 1
            return _SECRET_SHAPED.sub(REDACTED, node)
        return node

    return walk(value), count
