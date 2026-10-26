"""What the secret-shape pattern redacts, compared with what it redacted before ticket #53.

Pull request 59 made the pattern linear with a look-behind that lets a token start only where a run of token
characters begins (a token character is a letter, a digit, `_` or `-`). That version left a token readable whenever it
was glued to a letter, digit, `_` or `-` in front of it (`Bearer%20<token>`, `\\n<token>`, `x-<token>`): a truncated
token, an opaque-payload token and an unsigned token were not redacted at all, and a normal token kept its header. The
pattern in `redaction.py` redacts from the start of the run, and four of its alternatives (`AccountKey=`,
`SharedAccessKey=`, `sig=`, the private key header) can be followed by a glued token, so these tests state exactly what
is guaranteed, with the reference pattern kept in `redaction_fixtures.py` (the pattern before the ticket) as the
yardstick.

What is guaranteed (a, b) and what is bounded (c):

(a) For every text built from the documented atoms, where atoms are separated by a space or another character that is
    not a token character, or sit in one of the enumerated glued layouts (a preceding string glued to a token, a key
    value or private key header followed directly, or after `_` or `-`, by a token), everything the reference pattern
    redacts is redacted by the engine's pattern, and any extra redacted character is a token character in a run in
    which the reference redacted something. The enumerated layouts are checked exhaustively and in seeded random
    sequences.
(b) Named table-driven cases: each token shape (three-part, truncated two-part, opaque payload, unsigned with a
    trailing dot, five-part encrypted) after each preceding string, and each key value or header followed by a glued
    token, give exactly the expected text.
(c) A seeded fuzz over the whole alternation, with the keyword atoms glued together in any order, loses nothing the
    reference redacted except in one counted case: a match of the engine's pattern ends strictly inside a match of the
    reference that begins inside it ("a cut"). The case seen is a token whose second segment runs straight into a
    keyword (`<token>.<segment>AccountKey=<value>`); the token now takes the segment up to the `=`. The reference had
    the same boundary unless a preceding `ghp_` match pre-empted the token. The number of texts with a cut is bounded
    below, and a loss that is not a cut fails the test.

Not guaranteed, and unchanged: a match stops at the end of the second segment, so the signature of a three-part token
stays readable (`tail` in `redaction_fixtures.Shape`).

The harness is checked against the two earlier versions of the pattern (the look-behind-only one and the bare
JSON-web-token fix without the key tails): both must fail it, so it cannot go blind.
"""

from __future__ import annotations

import random
import re

import pytest
from cloud_crawler_core import redaction
from cloud_crawler_core.redaction import REDACTED, redact_payload, scrub
from redaction_fixtures import (
    KEYWORD_UNITS,
    OLD_SECRET_SHAPED,
    PRECEDING_BOUNDARY,
    PRECEDING_GLUED,
    SHAPES,
    armor,
    differences_from_old,
    expected_after,
    redacted_mask,
)

ENGINE = redaction._SECRET_SHAPED

# The two earlier versions of the pattern, kept only to prove that this file fails them.
_KEYS = (
    r"AccountKey=[A-Za-z0-9+/=]{20,}",
    r"SharedAccessKey=[A-Za-z0-9+/=]{20,}",
    r"sig=[A-Za-z0-9%+/=]{20,}",
)
_REST = r"|ghp_[A-Za-z0-9]{20,}|" + "-" * 5 + "BEGIN [A-Z ]*PRIVATE KEY" + "-" * 5 + ")"
LOOKBEHIND_ONLY = re.compile(  # pull request 59: a token may start only at the start of a run, nothing else changed
    "("
    + _KEYS[0]
    + "|"
    + _KEYS[1]
    + r"|(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}+\.[A-Za-z0-9_-]{10,}|"
    + _KEYS[2]
    + _REST
)
_BARE_TOKEN = r"(?<![A-Za-z0-9_-])(?:(?!eyJ)[A-Za-z0-9_-])*+eyJ[A-Za-z0-9_-]{10,}+\.[A-Za-z0-9_-]{10,}"
BARE_TOKEN_FIX = (
    re.compile(  # the token alternative of the engine's pattern, without the tail on the other alternatives
        "(" + _KEYS[0] + "|" + _KEYS[1] + "|" + _BARE_TOKEN + "|" + _KEYS[2] + _REST
    )
)

ALL_SHAPES = sorted(SHAPES)


# ---------------------------------------------------------------------------------------------------------------------
# (b) Named cases
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("shape_name", ALL_SHAPES)
@pytest.mark.parametrize("prefix", PRECEDING_GLUED, ids=lambda p: repr(p))
def test_a_token_glued_to_what_precedes_it_is_redacted_with_the_characters_that_touch_it(shape_name, prefix):
    shape = SHAPES[shape_name]
    for lead, trail in (("", ""), ("x ", ""), ("x ", " end"), ("", '"')):
        text = lead + prefix + shape.text + trail
        expected = lead + expected_after(prefix, shape) + trail
        redacted = ENGINE.sub(REDACTED, text)
        assert redacted == expected
        assert all(part not in redacted for part in shape.parts.values())
        out, count = redact_payload({"x": text})
        assert out["x"] == expected and count == 1
        assert scrub(text) == expected


@pytest.mark.parametrize("shape_name", ALL_SHAPES)
@pytest.mark.parametrize("prefix", PRECEDING_BOUNDARY, ids=lambda p: repr(p))
def test_a_token_after_an_ordinary_boundary_is_redacted_as_it_always_was(shape_name, prefix):
    shape = SHAPES[shape_name]
    for lead, trail in (("", ""), ("x ", " end")):
        text = lead + prefix + shape.text + trail
        assert (
            ENGINE.sub(REDACTED, text)
            == OLD_SECRET_SHAPED.sub(REDACTED, text)
            == lead + prefix + REDACTED + shape.tail + trail
        )


@pytest.mark.parametrize("shape_name", ALL_SHAPES)
@pytest.mark.parametrize("unit_name", sorted(KEYWORD_UNITS))
def test_a_token_glued_behind_a_key_value_or_a_key_header_is_redacted_with_it(unit_name, shape_name):
    unit, glues = KEYWORD_UNITS[unit_name]
    shape = SHAPES[shape_name]
    for glue in glues:
        for lead, trail in (("", ""), ("a=", ";b=1"), ("x ", " end")):
            text = lead + unit + glue + shape.text + trail
            expected = lead + REDACTED + shape.tail + trail
            redacted = ENGINE.sub(REDACTED, text)
            assert redacted == expected, (unit_name, glue, shape_name)
            assert all(part not in redacted for part in shape.parts.values())
            assert redact_payload({"x": text})[0]["x"] == expected
            # what the reference did: both pieces were redacted, with the glue character left between them
            assert OLD_SECRET_SHAPED.sub(REDACTED, text) == lead + REDACTED + glue + REDACTED + shape.tail + trail


def test_two_tokens_glued_to_each_other_are_both_redacted():
    three, two = SHAPES["three-part"], SHAPES["truncated-two-part"]
    text = three.text + two.text  # the first token's signature runs into the second token's header
    redacted = ENGINE.sub(REDACTED, text)
    assert two.parts["header"] not in redacted and two.parts["claims"] not in redacted
    assert three.parts["header"] not in redacted and three.parts["claims"] not in redacted


@pytest.mark.parametrize(
    "text",
    [
        "{t}",
        "token {t} leaked",
        "Authorization: Bearer {t}",
        "Authorization%3A%20Bearer%20{t}",
        'header "{t}"',
        'header \\"{t}\\"',
        "access_token={t}&state=1",
        "https://example.invalid/cb?u=https%3A%2F%2Fexample.invalid%2Fp%3Faccess_token%3D{t}",
        "key:{t}",
        "path/{t}",
        "line one\\n{t}\\nline three",
        "line one\n{t}\nline three",
        "b'x {t}'",
        "ValueError: bad token {t} in header",
        '{{"value":"{t}"}}',
        "{{'k': '{t}'}}",
    ],
)
@pytest.mark.parametrize("shape_name", ALL_SHAPES)
def test_a_token_is_redacted_in_the_places_it_turns_up(text, shape_name):
    shape = SHAPES[shape_name]
    wrapped = text.format(t=shape.text)
    out, count = redact_payload({"x": wrapped})
    assert count == 1 and REDACTED in out["x"]
    assert all(part not in out["x"] for part in shape.parts.values()), out["x"]
    assert all(part not in scrub(wrapped) for part in shape.parts.values())


# ---------------------------------------------------------------------------------------------------------------------
# (a) The enumerated layouts, checked against the reference pattern
# ---------------------------------------------------------------------------------------------------------------------


def _units() -> list[tuple[str, str]]:
    """The documented atoms and the enumerated glued layouts, each as (label, text)."""
    units: list[tuple[str, str]] = []
    for shape in SHAPES.values():
        units.append((shape.name, shape.text))
        for prefix in PRECEDING_GLUED + PRECEDING_BOUNDARY:
            units.append((f"{prefix!r}+{shape.name}", prefix + shape.text))
    for name, (unit, glues) in KEYWORD_UNITS.items():
        units.append((name, unit))
        for glue in glues:
            for shape in SHAPES.values():
                units.append((f"{name}+{glue!r}+{shape.name}", unit + glue + shape.text))
    return units


UNITS = _units()
SEPARATORS = (" ", "\n", ", ", '" ', "; ", "&", " = ")


def test_the_enumerated_layouts_keep_everything_the_reference_redacted():
    failures = {}
    for label, unit in UNITS:
        for lead, trail in (("x ", ""), ("", " end"), ('"', '"')):
            text = lead + unit + trail
            problems = differences_from_old(ENGINE, text)
            if problems:
                failures[label] = (text, problems[:2])
    assert not failures, failures


def test_random_sequences_of_the_documented_atoms_keep_everything_the_reference_redacted():
    rng = random.Random(20261026)
    failures = []
    for _ in range(20_000):
        text = rng.choice(SEPARATORS).join(rng.choice(UNITS)[1] for _ in range(rng.randint(1, 5)))
        problems = differences_from_old(ENGINE, text)
        if problems:
            failures.append((text, problems[:2]))
    assert not failures, failures[:3]


# ---------------------------------------------------------------------------------------------------------------------
# (c) The whole alternation, atoms glued in any order
# ---------------------------------------------------------------------------------------------------------------------

FUZZ_ATOMS = [
    "eyJ", "eyJ", "eyJ" + "a" * 12, ".", ".", "b" * 12, "A", "b", "_", "-", " ", "=", "%20", "\\n", '"', "+", "/",
    "sig=", "AccountKey=", "SharedAccessKey=", "ghp_", "A" * 20, "k" * 12, "-" * 5, "BEGIN ", "PRIVATE KEY",
    armor("PRIVATE KEY"), armor("RSA PRIVATE KEY"), "sig=" + "A" * 20, "AccountKey=" + "A" * 20,
    "SharedAccessKey=" + "A" * 20, "ghp_" + "A" * 20,
]  # fmt: skip
FUZZ_ROUNDS = 300_000
FUZZ_SEED = 20261026
MAX_CUT_FRACTION = (
    0.0003  # measured about 0.00008 (a few dozen texts in 300,000); a change that makes cuts common must fail
)


def whole_alternation_fuzz(pattern: re.Pattern[str], rounds: int, seed: int) -> dict[str, int]:
    """Count the fuzz texts in which `pattern` leaves readable something the reference redacted: `uncut` when no match
    of `pattern` cuts the reference match (a plain loss) and `cut` when one does (the counted case)."""
    rng = random.Random(seed)
    counts = {"texts": 0, "uncut": 0, "cut": 0}
    for _ in range(rounds):
        text = "".join(rng.choice(FUZZ_ATOMS) for _ in range(rng.randint(1, 12)))
        mask = redacted_mask(pattern, text)
        spans = [m.span() for m in pattern.finditer(text)]
        lost_plain = lost_cut = False
        for match in OLD_SECRET_SHAPED.finditer(text):
            start, end = match.span()
            if all(mask[start:end]):
                continue
            if any(s <= start < e < end for s, e in spans):
                lost_cut = True
            else:
                lost_plain = True
        counts["texts"] += 1
        counts["uncut"] += lost_plain
        counts["cut"] += lost_cut
    return counts


def test_the_whole_alternation_loses_nothing_except_the_counted_cut_case():
    counts = whole_alternation_fuzz(ENGINE, FUZZ_ROUNDS, FUZZ_SEED)
    assert counts["uncut"] == 0, counts
    assert counts["cut"] <= FUZZ_ROUNDS * MAX_CUT_FRACTION, counts


def test_the_cut_case_is_what_the_comment_in_redaction_py_says_it_is():
    # `<token>.<segment>AccountKey=<value>`: the token takes the segment up to the `=`, so the value stays readable.
    token = "eyJ" + "a" * 12 + "." + "b" * 12
    value = "V" * 24
    glued = f"{token}AccountKey={value}"
    # Without a `ghp_` match in front, the engine's pattern and the reference agree: the value stays readable in both.
    assert ENGINE.sub(REDACTED, glued) == OLD_SECRET_SHAPED.sub(REDACTED, glued) == REDACTED + "=" + value
    # With a `ghp_` match in front the reference could not start the token, so it redacted the value and left the
    # token's second segment readable. The engine's pattern reads the same text the other way round. This is the
    # counted case (a cut): one piece of a glued pair of secrets is left, where the reference left the other.
    preempted = f"ghp_{'t' * 24}{glued}"
    assert OLD_SECRET_SHAPED.sub(REDACTED, preempted) == REDACTED + "." + "b" * 12 + REDACTED
    assert ENGINE.sub(REDACTED, preempted) == REDACTED + "=" + value


# ---------------------------------------------------------------------------------------------------------------------
# The harness must fail the earlier versions
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("pattern", [LOOKBEHIND_ONLY, BARE_TOKEN_FIX], ids=["look-behind-only", "bare-token-fix"])
def test_the_checks_above_fail_the_earlier_versions_of_the_pattern(pattern):
    failing_units = [label for label, unit in UNITS if differences_from_old(pattern, "x " + unit)]
    assert failing_units, "the enumerated layouts no longer tell this version from the reference"
    counts = whole_alternation_fuzz(pattern, 50_000, FUZZ_SEED)
    assert counts["uncut"] > 0, counts


def test_the_look_behind_only_version_left_a_glued_token_readable():
    # The defect that this file exists for, shown on the version that had it.
    shape = SHAPES["truncated-two-part"]
    leaked = LOOKBEHIND_ONLY.sub(REDACTED, "Bearer%20" + shape.text)
    assert shape.parts["header"] in leaked and shape.parts["claims"] in leaked
    assert redaction._SECRET_SHAPED.sub(REDACTED, "Bearer%20" + shape.text) == "Bearer%" + REDACTED
