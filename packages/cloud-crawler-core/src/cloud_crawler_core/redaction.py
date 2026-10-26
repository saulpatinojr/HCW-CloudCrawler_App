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
# Every alternative must take time linear in the text, because `redact_payload` runs this over every string of
# everything that is ingested and `scrub` over every exception message.
#
# The JSON web token (`eyJ<10 or more token characters>.<10 or more token characters>`; a token character is a letter,
# a digit, `_` or `-`) used to be quadratic on a long run of `eyJ` with no dot: each `eyJ` in the run started a scan to
# the end of the run. It is now written as `_TOKEN_IN_RUN`. From the start of a run of token characters it skips,
# possessively (no giving characters back), the part of the run in front of the run's FIRST `eyJ`, then matches what the
# old pattern matched from that `eyJ`. Whether the old pattern matched anywhere in a run depended only on the run's
# first `eyJ` (every later one has fewer characters after it), so the same runs match. The only difference is that the
# characters of the run in front of that `eyJ` (the `20` of `Bearer%20eyJ...`) are redacted as well. What makes it
# linear is the look-behind (a run is entered once, at its start) together with the prefix skip (the run is read once
# from there). The possessive quantifiers are defence in depth: with the look-behind in place the greedy form is linear
# too. Possessive quantifiers need Python 3.11 or later; the engine requires 3.14.
#
# The look-behind reads the original text, including characters an earlier match has already consumed. The
# `AccountKey=`, `SharedAccessKey=` and `sig=` values and the private key header can stop in the middle of a run (their
# value classes leave out `_` and `-`, and the header ends in hyphens), so a token glued right behind one of them would
# never be entered at a run start. Those four alternatives therefore end with `_GLUED_TOKEN`, the same pattern made
# optional: a token that follows in the rest of the run is redacted together with them. Each of them reads the rest of
# its own run at most once and runs do not overlap, so this stays linear. `ghp_` needs no tail: the token alternative is
# tried before it at the start of its run.
#
# Not covered: when two matches meet with no separator the boundaries can differ from the old pattern. The case that
# has been seen is a token whose second segment runs straight into a keyword, `<token>.<segment>AccountKey=<value>`.
# The token now takes the whole segment up to the `=`, so the keyword's value is left visible. The old pattern left it
# visible too, unless an earlier `ghp_` match happened to pre-empt the token. The test file
# test_redaction_secret_shaped.py counts these cases and states the bound. Also unchanged: a match stops at the end of
# the SECOND segment, so the signature of a three-part token stays visible.
#
# The other alternatives start with a fixed literal and end with an open quantifier, so they were already linear.
# tests/test_redaction_linear_time.py runs every pattern in this module against a hostile set and compares two text
# sizes, so a pattern added later is checked without being listed.
_TOKEN_IN_RUN = r"(?:(?!eyJ)[A-Za-z0-9_-])*+eyJ[A-Za-z0-9_-]{10,}+\.[A-Za-z0-9_-]{10,}"
_GLUED_TOKEN = "(?:" + _TOKEN_IN_RUN + ")?"
_SECRET_SHAPED = re.compile(
    "("
    + "|".join(
        (
            r"AccountKey=[A-Za-z0-9+/=]{20,}" + _GLUED_TOKEN,
            r"SharedAccessKey=[A-Za-z0-9+/=]{20,}" + _GLUED_TOKEN,
            r"(?<![A-Za-z0-9_-])" + _TOKEN_IN_RUN,
            r"sig=[A-Za-z0-9%+/=]{20,}" + _GLUED_TOKEN,
            r"ghp_[A-Za-z0-9]{20,}",
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----" + _GLUED_TOKEN,
        )
    )
    + ")"
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
        "decision_accepted",
        "drift_evaluated",
        "proposal_created",
        "review_decided",
        "collection_run",
        "azure_mcp_call",
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
        "draft",
        "accepted",
        "approve",
        "reject",
        "retirement",
        "contradiction",
        "advisor",
        "cost",
        "expiry",
        "supersession",
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
        "invalid_state",
        "not_configured",
        "tool_not_allowed",
        "no_recording",
        "no_recordings",
        "tool_error",
        "server_version",
        "not_open",
        "off",
        "stdio",
        "recorded",
        "subscription_list",
        "group_list",
        "group_resource_list",
        "advisor_recommendation_list",
        "advisor_recommendation_summary",
        "advisor_metadata_list",
        "advisor_metadata_get",
        "advisor_remediation_get",
        "policy_assignment_list",
        "pricing_get",
        "wellarchitectedframework_serviceguide_get",
        "cloudarchitect_design",
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
