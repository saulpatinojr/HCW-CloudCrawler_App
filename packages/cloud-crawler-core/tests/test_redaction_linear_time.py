"""Every redaction pattern takes time linear in the text (ticket #53).

`redact_payload` runs the secret-shape pattern over every string of everything that is ingested, and `scrub` over every
exception message, so a pattern that is quadratic on a crafted value lets one upload hold the whole process (and, with
the interpreter's global lock, every other thread) for seconds. The first version of the JSON web token alternative was:
a long run of `eyJ` with no dot took about a second per 64 KB string.

The check compares two sizes instead of timing one against a constant, so it holds on a slow or busy runner: a
linear pattern takes 8 to 14 times longer on a text 8 times longer (the larger text no longer fits the processor's
first-level cache), a quadratic one 55 to 64 times longer, and the limit sits between them. Each measurement is the
best of several batches, which discards the batches a busy machine slowed down, and a result over the limit is
measured again before it fails, because noise does not repeat and a quadratic pattern does. The patterns are
discovered in the module, so a pattern added later is checked against the whole hostile set without anyone
remembering to list it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from collections.abc import Callable

import pytest
from cloud_crawler_core import redaction
from cloud_crawler_core.redaction import REDACTED, redact_payload, scrub

SMALL = 16_384
LARGE = 8 * SMALL  # 131,072 characters
MAX_RATIO = 24.0  # linear is 8 to 14 (cache effects), quadratic about 55 to 64
DOT_FREE_RUN = 65_535  # the length from the ticket

# The pattern as it was before the fix, kept to prove that this check would have caught it.
LEGACY_JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")


BEGIN = "-" * 5 + "BEGIN "  # the start of a PEM armor line, built at run time (see `armor`)


def armor(label: str) -> str:
    """A PEM armor line, `-----BEGIN <label>-----`, built at run time so that no key header sits in the source for a
    secret scanner (the repository's gitleaks step reads every commit) to flag. Only the header is ever needed: the
    pattern looks at the header alone."""
    return f"{BEGIN}{label}" + "-" * 5


def _per_call_seconds(
    call: Callable[[str], object], text: str, *, trials: int = 4, batch_seconds: float = 0.004
) -> float:
    """Best time of one call. Cheap calls are repeated in batches long enough to time (the batch size doubles until a
    batch takes `batch_seconds`); a slow call, which a quadratic pattern is, is timed once, because one sample is
    already conclusive and repeating it would take minutes."""
    reps = 1
    while True:
        started = time.perf_counter()
        for _ in range(reps):
            call(text)
        elapsed = time.perf_counter() - started
        if elapsed > 0.25 and reps == 1:
            return elapsed
        if elapsed >= batch_seconds:
            break
        reps *= 2
    best = elapsed / reps
    for _ in range(trials):
        started = time.perf_counter()
        for _ in range(reps):
            call(text)
        best = min(best, (time.perf_counter() - started) / reps)
    return best


def _growth(call: Callable[[str], object], build: Callable[[int], str], *, attempts: int = 3) -> float:
    """How many times longer the call takes on the large text than on the small one. A measurement that comes out over
    the limit is repeated, and the smallest ratio counts: noise from a busy machine does not repeat, a quadratic
    pattern does."""
    small, large = build(SMALL), build(LARGE)
    ratio = float("inf")
    for _ in range(attempts):
        ratio = min(ratio, _per_call_seconds(call, large) / _per_call_seconds(call, small))
        if ratio < MAX_RATIO:
            break
    return ratio


def _repeat(unit: str) -> Callable[[int], str]:
    return lambda n: unit * max(1, n // len(unit))


def _padded(unit: str, tail: str = "") -> Callable[[int], str]:
    return lambda n: unit * max(1, n // len(unit)) + tail


# Each family is a text of about n characters that is the worst case for some way of writing a pattern: a fixed prefix
# repeated with nothing after it, repeated with a tail that is one character too short, a long run of allowed
# characters, many dots, and the same for every literal the module looks for.
HOSTILE: dict[str, Callable[[int], str]] = {
    "eyj-repeats-without-a-dot": _repeat("eyJ"),
    "eyj-repeats-then-a-short-second-segment": _padded("eyJ", ".a"),
    "eyj-repeats-after-a-complete-first-segment": lambda n: "eyJ" + "a" * 12 + "." + "eyJ" * (n // 3),
    "eyj-with-a-dot-each": _repeat("eyJ."),
    "eyj-segments-one-character-short": _repeat("eyJ" + "a" * 9 + "." + "b" * 9 + " "),
    "header-then-many-one-character-segments": lambda n: "eyJ" + "a" * 12 + ".b" * (n // 2),
    "only-dots": _repeat("."),
    "only-letters": _repeat("A"),
    "only-hyphens": _repeat("-"),
    "only-underscores": _repeat("_"),
    "only-equals-signs": _repeat("="),
    "only-spaces": _repeat(" "),
    "long-token-run-ending-in-a-bang": lambda n: "eyJ" + "A" * n + "!",
    "account-key-repeats": _repeat("AccountKey="),
    "account-key-one-character-short": _repeat("AccountKey=" + "A" * 19 + " "),
    "shared-access-key-repeats": _repeat("SharedAccessKey="),
    "shared-access-key-one-character-short": _repeat("SharedAccessKey=" + "A" * 19 + " "),
    "signature-repeats": _repeat("sig="),
    "signature-one-character-short": _repeat("sig=" + "A" * 19 + " "),
    "github-token-repeats": _repeat("ghp_"),
    "github-token-one-character-short": _repeat("ghp_" + "A" * 19 + " "),
    "private-key-header-repeats": _repeat(BEGIN),
    "private-key-header-then-capitals": lambda n: BEGIN + "A " * (n // 2),
    "private-key-header-then-the-word-repeated": lambda n: BEGIN + "PRIVATE " * (n // 8),
    "private-key-headers-each-with-capitals": _repeat(BEGIN + "A" * 20 + " "),
    # A key value or a private key header can end in the middle of a run of token characters, and then the same token
    # pattern reads the rest of that run: chains of them, followed by long runs of `eyJ` with and without dots.
    "key-value-then-a-hyphen-then-eyj-repeats": lambda n: "sig=" + "A" * 20 + "-" + "eyJ" * (n // 3),
    "key-value-then-an-underscore-then-a-long-token-run": lambda n: "AccountKey=" + "A" * 20 + "_eyJ" + "A" * n + "!",
    "key-values-each-followed-by-a-token-start": _repeat("SharedAccessKey=" + "A" * 20 + "-eyJ" + "a" * 12 + " "),
    "key-values-each-followed-by-a-complete-token": _repeat(
        "sig=" + "A" * 20 + "-eyJ" + "a" * 12 + "." + "b" * 12 + " "
    ),
    "key-values-glued-in-a-chain": _repeat("sig=" + "A" * 20 + "-"),
    "account-keys-glued-in-a-chain-with-eyj": _repeat("AccountKey=" + "A" * 20 + "_eyJ"),
    "private-key-header-then-eyj-repeats": lambda n: armor("PRIVATE KEY") + "eyJ" * (n // 3),
    "private-key-headers-glued-in-a-chain": _repeat(armor("PRIVATE KEY")),
    "private-key-headers-each-followed-by-token-starts": _repeat(armor("PRIVATE KEY") + "eyJ" * 4 + " "),
    "token-run-ending-just-before-a-key": lambda n: "eyJ" + "A" * n + "AccountKey=",
    "github-token-values-glued-in-a-chain": _repeat("ghp_" + "A" * 20 + "-"),
    "token-starts-each-followed-by-a-key-value": _repeat("eyJ" + "sig=" + "A" * 20 + "-"),
    "subscription-path-repeats": _repeat("/subscriptions/"),
    "subscription-path-one-per-line": _repeat("/subscriptions/x\n"),
    "guid-prefix-repeats": _repeat("aaaaaaaa-aaaa-aaaa-aaaa-"),
    "hex-and-hyphens": _repeat("0123456789abcdef-"),
    "quote-and-backslash": _repeat('\\"'),
}

PATTERNS: dict[str, re.Pattern[str]] = {
    name: value for name, value in sorted(vars(redaction).items()) if isinstance(value, re.Pattern)
}


def test_the_module_still_has_the_patterns_this_file_checks():
    # If this fails a pattern was renamed or removed; check the new shape of the module rather than loosen the test.
    assert {"_GUID", "_SUBSCRIPTION_PATH", "_SECRET_SHAPED", "_DENIED_KEYS"} <= set(PATTERNS)


@pytest.mark.parametrize("family", sorted(HOSTILE))
@pytest.mark.parametrize("name", sorted(PATTERNS))
def test_a_pattern_takes_time_linear_in_the_text(name, family):
    pattern = PATTERNS[name]

    def call(text: str) -> object:
        return pattern.search(text), pattern.sub(REDACTED, text)

    ratio = _growth(call, HOSTILE[family])
    assert ratio < MAX_RATIO, f"{name} on {family}: {ratio:.1f}x slower on 8x the text (linear is about 8, limit 24)"


def test_a_very_long_key_is_matched_in_linear_time():
    # `_DENIED_KEYS` is applied to a key, not to a value, so the generic check above only reaches it through text.
    def call(text: str) -> object:
        return redact_payload({text: 1})

    for build in (_repeat("password"), _repeat("pass"), _repeat("A"), _repeat("-_")):
        assert _growth(call, build) < MAX_RATIO


@pytest.mark.parametrize("family", ["eyj-repeats-without-a-dot", "eyj-repeats-then-a-short-second-segment"])
def test_scrub_and_redact_payload_are_linear_on_repeated_token_starts(family):
    build = HOSTILE[family]
    assert _growth(scrub, build) < MAX_RATIO
    assert _growth(lambda text: redact_payload({"description": [text, {"deeper": text}]}), build) < MAX_RATIO


def test_the_length_from_the_ticket_is_redacted_or_left_alone_in_a_few_milliseconds():
    # A coarse sanity bound as well as the ratio: 65,535 characters took about a second before the fix. The limit is
    # far above the 1-3 ms measured so a slow runner passes, and far below the old time.
    text = "eyJ" * (DOT_FREE_RUN // 3)
    assert _per_call_seconds(scrub, text) < 0.25
    out, count = redact_payload({"value": text})
    assert out == {"value": text} and count == 0  # nothing to redact: no dot, so not a token


def test_the_check_itself_would_have_caught_the_old_pattern():
    # The legacy pattern is quadratic. If this stops failing the ratio check above has become blind (for example by a
    # timer that is too coarse, or a limit that was loosened), and it must not be trusted.
    def call(text: str) -> object:
        return LEGACY_JWT_PATTERN.search(text)

    small, large = 3_000, 24_000
    ratio = _per_call_seconds(call, "eyJ" * (large // 3)) / _per_call_seconds(call, "eyJ" * (small // 3))
    assert ratio > MAX_RATIO, f"the old pattern grew only {ratio:.1f}x on 8x the text"


def test_the_check_would_also_have_caught_a_required_key_tail():
    # The key alternatives end with the token pattern, optional. Made required, `sig=<long value>` tries the token
    # pattern at every shorter value and is quadratic on `sig=` repeated (the families `signature-repeats`,
    # `account-key-repeats` and `shared-access-key-repeats` above). The control keeps those families honest, as the
    # legacy pattern does for the `eyJ` ones.
    required = re.compile("(sig=[A-Za-z0-9%+/=]{20,}(?:" + redaction._TOKEN_IN_RUN + "))")
    small, large = _repeat("sig=")(1_000), _repeat("sig=")(8_000)
    ratio = _per_call_seconds(required.search, large) / _per_call_seconds(required.search, small)
    assert ratio > MAX_RATIO, f"a required key tail grew only {ratio:.1f}x on 8x the text"


# ---------------------------------------------------------------------------------------------------------------------
# The patterns must still redact what they redacted before.
# ---------------------------------------------------------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def fictional_jwt() -> str:
    """A three-part token of the real shape (header and payload are base64url of JSON, so the header starts `eyJ`),
    built at run time from fictional claims so that no token-shaped literal sits in the source for a secret scanner."""
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = {"sub": "hcw-sample-user", "name": "Sample Person", "iat": 1_700_000_000}
    payload = _b64url(json.dumps(claims).encode())
    signature = _b64url(hashlib.sha256(b"fictional signing input").digest())
    return f"{header}.{payload}.{signature}"


def test_the_fictional_token_has_the_real_shape():
    token = fictional_jwt()
    assert token.startswith("eyJ") and token.count(".") == 2


@pytest.mark.parametrize(
    "template",
    [
        "{t}",
        "token {t} leaked",
        "Authorization: Bearer {t}",
        'header "{t}"',
        "access_token={t}&state=1",
        "key:{t}",
        "path/{t}",
        "({t})",
        "[{t}]",
        "line one\n{t}\nline three",
        "tab\t{t}",
        "before.{t}",
        "{t} after",
        '{{"value":"{t}"}}',
    ],
)
def test_a_real_shaped_token_is_redacted_wherever_a_boundary_precedes_it(template):
    token = fictional_jwt()
    header, payload, signature = token.split(".")
    text = template.format(t=token)
    assert redaction._SECRET_SHAPED.search(text)
    redacted = redaction._SECRET_SHAPED.sub(REDACTED, text)
    assert header not in redacted and payload not in redacted
    assert REDACTED in redacted
    out, count = redact_payload({"x": text})
    assert out["x"] == redacted and count == 1
    assert header not in scrub(text) and payload not in scrub(text)


def test_the_match_covers_the_header_and_payload_of_the_token():
    token = fictional_jwt()
    header, payload, _ = token.split(".")
    match = redaction._SECRET_SHAPED.search(f"x {token} y")
    assert match is not None
    assert match.group(0) == f"{header}.{payload}"


def test_a_token_glued_to_a_preceding_word_character_is_redacted_whole():
    # The pull request that made the pattern linear (59) let a token start only where a run of token characters begins,
    # and so left a token readable when its first segment was glued to a preceding letter, digit, `_` or `-`: the
    # header stayed, and a truncated, opaque or unsigned token stayed whole. The pattern now starts at the start of the
    # run, so the characters of the run in front of the token are redacted with it. The signature of a three-part token
    # stays readable, as it always did (a match stops at the end of the second segment). The table of shapes and
    # preceding strings is in test_redaction_secret_shaped.py.
    header, payload, signature = fictional_jwt().split(".")
    for glue in ("a", "Z", "7", "_", "-"):
        redacted = redaction._SECRET_SHAPED.sub(REDACTED, glue + ".".join((header, payload, signature)))
        assert redacted == f"{REDACTED}.{signature}"
        assert header not in redacted and payload not in redacted
        # a token of two segments has no second `eyJ` to fall back on, and is redacted whole all the same
        assert redaction._SECRET_SHAPED.sub(REDACTED, glue + header + "." + payload) == REDACTED
    assert redaction._SECRET_SHAPED.search("." + header + "." + payload) is not None  # a dot is not a token character


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("account key", "AccountKey=" + "k" * 24),
        ("account key with padding characters", "AccountKey=" + "ab+/" * 8 + "=="),
        ("shared access key", "SharedAccessKey=" + "k" * 24),
        ("shared access signature", "sig=" + "s" * 24),
        ("shared access signature, url-encoded", "sig=" + "ab%2B" * 6),
        ("github token", "ghp_" + "t" * 24),
        ("private key", armor("PRIVATE KEY")),
        ("RSA private key", armor("RSA PRIVATE KEY")),
        ("EC private key", armor("EC PRIVATE KEY")),
        ("encrypted private key", armor("ENCRYPTED PRIVATE KEY")),
        ("OpenSSH private key", armor("OPENSSH PRIVATE KEY")),
        # exactly the shortest text each alternative accepts, which pins the lengths in the pattern
        ("token at its shortest", "eyJ" + "a" * 10 + "." + "b" * 10),
        ("account key at its shortest", "AccountKey=" + "k" * 20),
        ("shared access key at its shortest", "SharedAccessKey=" + "k" * 20),
        ("shared access signature at its shortest", "sig=" + "s" * 20),
        ("github token at its shortest", "ghp_" + "t" * 20),
    ],
)
def test_every_other_secret_shape_is_still_redacted(label, text):
    for template in ("{t}", "value {t} end", "a={t};b=1"):
        wrapped = template.format(t=text)
        assert redaction._SECRET_SHAPED.search(wrapped), label
        assert text not in redaction._SECRET_SHAPED.sub(REDACTED, wrapped), label


@pytest.mark.parametrize(
    "text",
    [
        "eyJ" + "a" * 9 + "." + "b" * 10,  # first segment one character short
        "eyJ" + "a" * 10 + "." + "b" * 9,  # second segment one character short
        "eyJ" + "a" * 30,  # no dot
        "eyJ" + "a" * 10 + "!" + "b" * 10,  # not a dot
        "eyI" + "a" * 10 + "." + "b" * 10,  # not the header prefix
        "AccountKey=" + "k" * 19,
        "SharedAccessKey=" + "k" * 19,
        "sig=" + "s" * 19,
        "ghp_" + "t" * 19,
        armor("PUBLIC KEY"),
        armor("PRIVATE"),
    ],
)
def test_text_one_character_short_of_a_secret_shape_is_left_alone(text):
    assert redaction._SECRET_SHAPED.search(text) is None
    assert redact_payload(text) == (text, 0)


def test_two_tokens_in_one_value_are_both_redacted():
    token = fictional_jwt()
    out, count = redact_payload({"x": f"first {token} second {token} done"})
    assert out["x"].count(REDACTED) == 2 and count == 1  # one string replaced; `count` counts values, not matches
