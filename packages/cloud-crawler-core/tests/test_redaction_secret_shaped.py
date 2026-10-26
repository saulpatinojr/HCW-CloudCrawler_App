"""What the secret-shape pattern redacts, compared with what it redacted before ticket #53.

Pull request 59 made the pattern linear with a look-behind that lets a token start only where a run of token
characters begins (a token character is a letter, a digit, `_` or `-`). That version left a token readable whenever it
was glued to a letter, digit, `_` or `-` in front of it (`Bearer%20<token>`, `\\n<token>`, `x-<token>`): a truncated
token, an opaque-payload token and an unsigned token were not redacted at all, and a normal token kept its header. The
pattern in `redaction.py` redacts from the start of the run, and four of its alternatives (`AccountKey=`,
`SharedAccessKey=`, `sig=`, the private key header) can be followed by a glued token. These tests check it against the
pattern as it was before the ticket, kept in `redaction_fixtures.py` as the yardstick. They are checks on enumerated
layouts and on seeded samples, not a proof; the argument behind them is in the comment above `_TOKEN_IN_RUN` in
`redaction.py`.

What they check (a, b) and what they bound (c):

(a) For the texts built from the documented atoms, where atoms are separated by a space or another character that is
    not a token character, or sit in one of the enumerated glued layouts (a preceding string glued to a token, a key
    value or private key header followed directly, or after `_` or `-`, by a token), everything the reference pattern
    redacts is redacted by the engine's pattern, and any extra redacted character is a token character in a run in
    which the reference redacted something. The enumerated layouts are checked exhaustively (with three leads and
    trails) and in 20,000 seeded random sequences of up to five of them.
(b) Named table-driven cases: each token shape (three-part, truncated two-part, opaque payload, unsigned with a
    trailing dot, five-part encrypted) after each preceding string, and each key value or header followed by a glued
    token, give exactly the expected text.
(c) A seeded fuzz over the whole alternation, with the keyword atoms glued together in any order, loses nothing the
    reference redacted except in one counted case, a "cut": a match of the engine's pattern that begins before a
    reference match and ends strictly inside it. Two kinds are seen and bounded separately. A keyword cut: a token
    whose second segment runs straight into a keyword (`<token>.<segment>AccountKey=<value>`, the same with
    `SharedAccessKey=`, `sig=` or the private key header); the token takes the segment up to the `=` (or the space of
    the header), so the keyword's value stays readable. The reference had the same boundary unless a preceding `ghp_`
    match pre-empted the token. A signature cut: the reference redacted a token's second part and signature only
    because a preceding `ghp_` match pre-empted the first part; the engine's pattern redacts the whole token up to its
    second segment and leaves the signature, as it always does. Each count has a ceiling (1.25 times what the seeded
    fuzz measures, rounded up; the signature cut measures none with this seed), and any other loss fails the test.

Not covered, and unchanged: a match stops at the end of the second segment, so the signature of a three-part token
stays readable (`tail` in `redaction_fixtures.Shape`); a key value that runs straight into a token swallows the token's
first segment (the value classes take letters and digits), so the rest of the token stays readable.

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
    "SharedAccessKey=" + "A" * 20, "ghp_" + "A" * 20, "e", "y", "J", "%2B", ".eyJ", "\u00e9",
]  # fmt: skip
FUZZ_ROUNDS = 300_000
FUZZ_SEED = 20261026
# What the seeded fuzz measures for the engine's pattern is KEYWORD_CUTS_MEASURED texts with a keyword cut and
# SIGNATURE_CUTS_MEASURED with a signature cut (none with this seed; a wider run of 900,000 texts found one); the
# ceilings are 1.25 times the measurement, rounded up. A change that loses anything else, or makes cuts more common,
# fails, and so does a signature cut: if a new seed or new atoms produce one, read it before raising the ceiling.
KEYWORD_CUTS_MEASURED = 27
SIGNATURE_CUTS_MEASURED = 0
MAX_KEYWORD_CUTS = 34
MAX_SIGNATURE_CUTS = 0


def whole_alternation_fuzz(pattern: re.Pattern[str], rounds: int, seed: int) -> dict[str, int]:
    """Count the fuzz texts in which `pattern` leaves readable something the reference redacted. For each reference
    match that is not fully redacted: `keyword_cut` when a match of `pattern` begins before it and ends inside it, at
    the `=` of a keyword or the space of a private key header; `signature_cut` when such a match ends at the dot in
    front of a token's signature; `unexplained` for every other loss, including a match of `pattern` that begins at
    the same place and stops early."""
    rng = random.Random(seed)
    counts = {"texts": 0, "unexplained": 0, "keyword_cut": 0, "signature_cut": 0}
    for _ in range(rounds):
        text = "".join(rng.choice(FUZZ_ATOMS) for _ in range(rng.randint(1, 12)))
        mask = redacted_mask(pattern, text)
        spans = [m.span() for m in pattern.finditer(text)]
        seen = {"unexplained": False, "keyword_cut": False, "signature_cut": False}
        for match in OLD_SECRET_SHAPED.finditer(text):
            start, end = match.span()
            if all(mask[start:end]):
                continue
            cutters = [e for s, e in spans if s < start < e < end]
            if not cutters:
                seen["unexplained"] = True
            elif match.group(0).startswith("eyJ") and text[cutters[0]] == ".":
                seen["signature_cut"] = True
            elif not match.group(0).startswith("eyJ") and text[cutters[0]] in "= ":
                seen["keyword_cut"] = True
            else:
                seen["unexplained"] = True
        counts["texts"] += 1
        for kind, hit in seen.items():
            counts[kind] += hit
    return counts


def test_the_whole_alternation_loses_nothing_except_the_counted_cuts():
    counts = whole_alternation_fuzz(ENGINE, FUZZ_ROUNDS, FUZZ_SEED)
    assert counts["texts"] == FUZZ_ROUNDS
    assert counts["unexplained"] == 0, counts
    assert counts["keyword_cut"] <= MAX_KEYWORD_CUTS, counts
    assert counts["signature_cut"] <= MAX_SIGNATURE_CUTS, counts


@pytest.mark.parametrize(
    ("keyword", "closing"),
    [
        ("AccountKey=", "V" * 24),
        ("SharedAccessKey=", "V" * 24),
        ("sig=", "V" * 24),
        (armor("PRIVATE KEY")[:-5], "-----"),  # the header, whose "keyword" ends at the space after BEGIN
    ],
    ids=["account-key", "shared-access-key", "signature", "private-key-header"],
)
def test_the_cut_case_is_what_the_comment_in_redaction_py_says_it_is(keyword, closing):
    # `<token>.<segment><keyword><value>`: the token takes the segment up to the `=`, so the value stays readable.
    token = "eyJ" + "a" * 12 + "." + "b" * 12
    glued = f"{token}{keyword}{closing}"
    # Without a `ghp_` match in front, the engine's pattern and the reference agree: what follows the segment stays.
    assert ENGINE.sub(REDACTED, glued) == OLD_SECRET_SHAPED.sub(REDACTED, glued)
    assert closing in ENGINE.sub(REDACTED, glued)
    # With a `ghp_` match in front the reference could not start the token, so it redacted the keyword and its value
    # and left the token's second segment readable. The engine's pattern reads the same text the other way round.
    # This is a keyword cut: one piece of a glued pair of secrets is left, where the reference left the other.
    preempted = f"ghp_{'t' * 24}{glued}"
    old, new = OLD_SECRET_SHAPED.sub(REDACTED, preempted), ENGINE.sub(REDACTED, preempted)
    assert old.startswith(REDACTED + "." + "b" * 12) and "b" * 12 not in new
    assert new != old


def test_a_key_value_that_runs_into_a_token_swallows_its_first_segment_as_before():
    # The value classes take letters and digits, so `sig=<24 characters>eyJ...` has no break in front of the token: the
    # value takes the first segment, and the dot and the second segment stay readable. The reference did the same.
    token = "eyJ" + "a" * 12 + "." + "b" * 12
    text = "sig=" + "s" * 24 + token
    assert ENGINE.sub(REDACTED, text) == OLD_SECRET_SHAPED.sub(REDACTED, text) == REDACTED + "." + "b" * 12


def test_a_reference_ghp_match_next_to_a_token_left_its_second_segment_and_the_engine_redacts_it():
    # `ghp_<24>eyJ...` : the reference's `ghp_` match took the first segment, so only the dot and the second segment
    # stayed. The engine's token alternative starts at the start of the run and takes both segments.
    token = "eyJ" + "a" * 12 + "." + "b" * 12
    text = "ghp_" + "t" * 24 + token
    assert OLD_SECRET_SHAPED.sub(REDACTED, text) == REDACTED + "." + "b" * 12
    assert ENGINE.sub(REDACTED, text) == REDACTED


def test_a_non_ascii_letter_in_front_of_a_token_is_not_a_token_character():
    token = "eyJ" + "a" * 12 + "." + "b" * 12
    for text in ("\u00e9" + token, "\u0663" + token, "\uff21" + token):  # e acute, an Arabic digit, a full-width A
        assert ENGINE.sub(REDACTED, text) == OLD_SECRET_SHAPED.sub(REDACTED, text) == text[0] + REDACTED


# ---------------------------------------------------------------------------------------------------------------------
# The harness must fail the earlier versions
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("pattern", [LOOKBEHIND_ONLY, BARE_TOKEN_FIX], ids=["look-behind-only", "bare-token-fix"])
def test_the_checks_above_fail_the_earlier_versions_of_the_pattern(pattern):
    failing_units = [label for label, unit in UNITS if differences_from_old(pattern, "x " + unit)]
    assert failing_units, "the enumerated layouts no longer tell this version from the reference"
    counts = whole_alternation_fuzz(pattern, 50_000, FUZZ_SEED)
    assert counts["unexplained"] > 0, counts


def test_the_look_behind_only_version_left_a_glued_token_readable():
    # The defect that this file exists for, shown on the version that had it.
    shape = SHAPES["truncated-two-part"]
    leaked = LOOKBEHIND_ONLY.sub(REDACTED, "Bearer%20" + shape.text)
    assert shape.parts["header"] in leaked and shape.parts["claims"] in leaked
    assert redaction._SECRET_SHAPED.sub(REDACTED, "Bearer%20" + shape.text) == "Bearer%" + REDACTED
