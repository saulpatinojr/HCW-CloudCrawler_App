"""Building blocks for the secret-shape redaction tests (ticket #53): the reference pattern and fictional tokens.

Everything that looks like a secret is built at run time from fictional parts, so no token-shaped, key-shaped or
private-key-shaped literal sits in the source for a secret scanner (the repository's gitleaks step reads every commit).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass

from cloud_crawler_core.redaction import REDACTED

# A token character is a letter, a digit, `_` or `-`: the class the secret-shape pattern reads a token segment with.
TOKEN_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")

BEGIN = "-" * 5 + "BEGIN "  # the start of a PEM armor line


def armor(label: str) -> str:
    """A PEM armor line, `-----BEGIN <label>-----`. Only the header is ever needed: the pattern looks at it alone."""
    return f"{BEGIN}{label}" + "-" * 5


# The secret-shape pattern as it was before ticket #53 (and before the pull request that made it linear). It is
# quadratic on a long run of `eyJ`, so it is only ever run on short texts, but it is the reference for what the
# engine redacted: nothing that it redacted may be left visible by the engine's pattern, with the one documented
# exception tests/test_redaction_secret_shaped.py counts.
OLD_SECRET_SHAPED = re.compile(
    r"(AccountKey=[A-Za-z0-9+/=]{20,}"
    r"|SharedAccessKey=[A-Za-z0-9+/=]{20,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r"|sig=[A-Za-z0-9%+/=]{20,}"
    r"|ghp_[A-Za-z0-9]{20,}"
    r"|" + "-" * 5 + "BEGIN [A-Z ]*PRIVATE KEY" + "-" * 5 + ")"
)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class Shape:
    """One shape of token. `parts` are the segments that must not stay readable; `tail` is what the pattern has
    always left behind a match (it stops at the end of the second segment, so the signature of a three-part token
    stays), worked out from the reference pattern with the token after a space."""

    name: str
    text: str
    parts: dict[str, str]
    tail: str


def _shape(name: str, text: str, parts: dict[str, str]) -> Shape:
    reference = OLD_SECRET_SHAPED.sub(REDACTED, " " + text)
    assert reference.startswith(" " + REDACTED), name
    return Shape(name, text, parts, reference[len(" " + REDACTED) :])


def token_shapes() -> dict[str, Shape]:
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = b64url(json.dumps({"sub": "hcw-sample-user", "name": "Sample Person", "iat": 1_700_000_000}).encode())
    opaque = b64url(b"an opaque payload that is not a json object, long enough to pass")
    signature = b64url(hashlib.sha256(b"fictional signing input").digest())
    key, vector, cipher, tag = (
        "encryptedKeyEncryptedKey",
        "initVectorInitVector",
        "cipherTextCipherText",
        "authTagAuthTag",
    )
    shapes = [
        _shape("three-part", f"{header}.{claims}.{signature}", {"header": header, "claims": claims}),
        _shape("truncated-two-part", f"{header}.{claims}", {"header": header, "claims": claims}),
        _shape("opaque-payload", f"{header}.{opaque}.{signature}", {"header": header, "payload": opaque}),
        _shape("unsigned-trailing-dot", f"{header}.{claims}.", {"header": header, "claims": claims}),
        _shape("five-part-encrypted", f"{header}.{key}.{vector}.{cipher}.{tag}", {"header": header, "key": key}),
    ]
    return {shape.name: shape for shape in shapes}


SHAPES = token_shapes()

# What can stand directly in front of a token: nothing, text where a token character touches it (a percent-encoded
# space, an escaped newline in a JSON or repr dump, a hyphenated word, a letter, a digit, an underscore), and the
# ordinary boundaries that never mattered.
PRECEDING_GLUED = [
    "Bearer%20",  # a URL-encoded "Bearer "
    "%3D",  # a URL-encoded "="
    "%22",  # a URL-encoded quote
    "\\n",  # a backslash and an n: a newline inside a JSON string or a repr
    "\\u0022",  # a JSON-escaped quote
    "x-",
    "a",
    "7",
    "_",
]
PRECEDING_BOUNDARY = ["", " ", "Bearer ", "\n", '"', "=", ":", "/", "(", "."]


def trailing_run(text: str) -> str:
    """The token characters at the end of `text` (the part that shares a run with whatever follows)."""
    end = len(text)
    while end > 0 and text[end - 1] in TOKEN_CHARS:
        end -= 1
    return text[end:]


def expected_after(prefix: str, shape: Shape) -> str:
    """What `prefix + token` must become: the token is redacted together with the token characters of `prefix` that
    touch it, and what the pattern has always left behind a token stays."""
    run = trailing_run(prefix)
    return prefix[: len(prefix) - len(run)] + REDACTED + shape.tail


# Keyword values that the pattern redacts, and the token characters that can follow them without a break (`_` and `-`
# are not in the value classes of `AccountKey=`, `SharedAccessKey=` and `sig=`, so a value stops in front of them).
KEYWORD_UNITS: dict[str, tuple[str, tuple[str, ...]]] = {
    "signature": ("sig=" + "s" * 24, ("_", "-")),
    "signature-url-encoded": ("sig=" + "ab%2B" * 6, ("_", "-")),
    "account-key": ("AccountKey=" + "k" * 24, ("_", "-")),
    "account-key-with-padding": ("AccountKey=" + "ab+/" * 8 + "==", ("_", "-")),
    "shared-access-key": ("SharedAccessKey=" + "k" * 24, ("_", "-")),
    "private-key-header": (armor("PRIVATE KEY"), ("", "-", "_")),
    "rsa-private-key-header": (armor("RSA PRIVATE KEY"), ("", "-", "_")),
    "github-token": ("ghp_" + "t" * 24, ("_", "-")),
}


def runs_of(text: str) -> list[tuple[int, int]]:
    """The maximal runs of token characters in `text`, as (start, end) pairs."""
    found: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        if text[index] in TOKEN_CHARS:
            start = index
            while index < len(text) and text[index] in TOKEN_CHARS:
                index += 1
            found.append((start, index))
        else:
            index += 1
    return found


def redacted_mask(pattern: re.Pattern[str], text: str) -> list[bool]:
    mask = [False] * len(text)
    for match in pattern.finditer(text):
        for index in range(*match.span()):
            mask[index] = True
    return mask


def differences_from_old(pattern: re.Pattern[str], text: str) -> list[str]:
    """Where `pattern` departs from the reference on `text`, for texts built from the documented atoms (a space or
    another non-token character between atoms, or one of the enumerated glued layouts). Empty means it does not.

    1. Everything the reference redacts is redacted: no character is `missed`.
    2. Any extra redacted character is a token character, and it sits in a run of token characters in which the
       reference redacted something (the `20` of `Bearer%20<token>`, the `_` in `<key value>_<token>`).
    """
    old, new = redacted_mask(OLD_SECRET_SHAPED, text), redacted_mask(pattern, text)
    problems = [f"missed at {i}" for i, (was, now) in enumerate(zip(old, new, strict=True)) if was and not now]
    run_of = {i: span for span in runs_of(text) for i in range(*span)}
    for i, (was, now) in enumerate(zip(old, new, strict=True)):
        if now and not was:
            if text[i] not in TOKEN_CHARS:
                problems.append(f"extra non-token character at {i}")
            elif not any(old[k] for k in range(*run_of[i])):
                problems.append(f"extra character at {i} in a run the reference left alone")
    return problems
