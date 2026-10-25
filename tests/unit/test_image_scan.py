"""The scheduled image scan and its accepted-risk file, pinned as tests (ticket #15).

Three things are checked here. The accepted-risk file `.trivyignore.yaml` must give every entry an id, a reason, an
owner and an expiry date, and must not hold an entry past its expiry (a stale decision turns this test red on every
pull request until someone reads the entry again). The scan script must keep Trivy pinned by digest and keep the
hardening flags. The workflow must keep running weekly and by hand. These are static checks of the files; they do not
prove how Trivy or GitHub behave (the first scan and its results are recorded in the header of the register file and in
VALIDATION.md)."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / ".trivyignore.yaml"
SCRIPT = ROOT / "scripts" / "scan-image.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "image-scan.yml"
MAX_DAYS_AHEAD = 180
REQUIRED = ("id", "statement", "owner", "expired_at")
OPTIONAL = ("paths", "purls")
VULN_ID = re.compile(r"^(CVE-\d{4}-\d{4,}|GHSA(-[23456789cfghjmpqrvwx]{4}){3}|DSA-\d+-\d+|DLA-\d+-\d+)$")
OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def parse_register(text: str) -> list[dict[str, str]]:
    """Read the register: a `vulnerabilities:` list of flat entries; scalars are plain, quoted or `>-` folded blocks.

    The format is deliberately narrow (the repository has no YAML library and the tests use none). A line that does not
    fit is an error, so the file cannot drift into a shape this test does not understand."""
    entries: list[dict[str, str]] = []
    key = ""
    block = False
    seen_root = False
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line == "vulnerabilities: []":
            return []
        if line == "vulnerabilities:":
            seen_root = True
            continue
        if not seen_root:
            raise ValueError(f"line {number}: expected 'vulnerabilities:' first: {line!r}")
        start = re.fullmatch(r"  - (\w+): ?(.*)", line)
        field = re.fullmatch(r"    (\w+): ?(.*)", line)
        if start or field:
            match = start or field
            assert match is not None
            if start:
                entries.append({})
            if not entries:
                raise ValueError(f"line {number}: a field before the first '- ' entry")
            key, value = match.group(1), match.group(2).strip()
            if key in entries[-1]:
                raise ValueError(f"line {number}: {key} appears twice in one entry")
            block = value in (">-", ">", "|", "|-")
            entries[-1][key] = "" if block else value.strip("\"'")
        elif block and line.startswith("      "):
            joined = f"{entries[-1][key]} {line.strip()}"
            entries[-1][key] = joined.strip()
        else:
            raise ValueError(f"line {number}: not an entry, a field or a folded line: {line!r}")
    if not seen_root:
        raise ValueError("no 'vulnerabilities:' list")
    return entries


def problems(entries: list[dict[str, str]], today: date) -> list[str]:
    """Every way an accepted-risk entry is not acceptable; an empty list means the register is sound."""
    found: list[str] = []
    ids: list[str] = []
    for position, entry in enumerate(entries, start=1):
        label = entry.get("id") or f"entry {position}"
        for name in REQUIRED:
            if not entry.get(name, "").strip():
                found.append(f"{label}: no {name}")
        for name in entry:
            if name not in REQUIRED + OPTIONAL:
                found.append(f"{label}: unknown field {name}")
        if entry.get("id") and not VULN_ID.fullmatch(entry["id"]):
            found.append(f"{label}: id is not a CVE, GHSA, DSA or DLA identifier")
        if entry.get("id"):
            ids.append(entry["id"])
        if entry.get("statement") and len(entry["statement"].split()) < 12:
            found.append(f"{label}: the reason is too short to be checked by a stranger")
        if entry.get("owner") and not OWNER.fullmatch(entry["owner"]):
            found.append(f"{label}: owner is not a GitHub user name")
        raw = entry.get("expired_at", "").strip()
        if raw:
            try:
                expiry = date.fromisoformat(raw)
            except ValueError:
                found.append(f"{label}: expired_at {raw!r} is not a YYYY-MM-DD date")
            else:
                if expiry <= today:
                    found.append(f"{label}: expired on {expiry}; re-read the entry and renew or remove it")
                elif expiry > today + timedelta(days=MAX_DAYS_AHEAD):
                    found.append(f"{label}: expires {expiry}, more than {MAX_DAYS_AHEAD} days ahead")
    found.extend(f"{name}: listed more than once" for name in sorted({i for i in ids if ids.count(i) > 1}))
    return found


GOOD = {
    "id": "CVE-2026-0001",
    "statement": "the flawed tool is installed but nothing in the appliance runs it and the container has no shell",
    "owner": "saulpatinojr",
    "expired_at": "2027-01-23",
}
TODAY = date(2026, 10, 25)


def test_the_register_is_sound_today():
    entries = parse_register(REGISTER.read_text(encoding="utf-8"))
    assert problems(entries, date.today()) == []


def test_a_sound_entry_passes():
    assert problems([dict(GOOD)], TODAY) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"statement": ""}, "no statement"),
        ({"statement": "not reachable"}, "reason is too short"),
        ({"owner": ""}, "no owner"),
        ({"owner": "two words"}, "not a GitHub user name"),
        ({"expired_at": ""}, "no expired_at"),
        ({"expired_at": "next quarter"}, "not a YYYY-MM-DD date"),
        ({"expired_at": "2026-10-25"}, "expired on 2026-10-25"),
        ({"expired_at": "2026-01-01"}, "expired on 2026-01-01"),
        ({"expired_at": "2027-06-01"}, "more than 180 days ahead"),
        ({"id": "fake finding"}, "not a CVE, GHSA, DSA or DLA identifier"),
        ({"id": ""}, "no id"),
        ({"reason": "an extra field"}, "unknown field reason"),
    ],
)
def test_each_way_an_entry_can_be_wrong_is_reported(change, expected):
    entry = {**GOOD, **change}
    assert any(expected in line for line in problems([entry], TODAY)), problems([entry], TODAY)


def test_an_entry_missing_its_review_date_altogether_is_reported():
    entry = {k: v for k, v in GOOD.items() if k != "expired_at"}
    assert problems([entry], TODAY) == [f"{GOOD['id']}: no expired_at"]


def test_a_duplicate_id_is_reported():
    assert "CVE-2026-0001: listed more than once" in problems([dict(GOOD), dict(GOOD)], TODAY)


def test_the_parser_reads_quoted_plain_and_folded_values():
    text = (
        "# comment\nvulnerabilities:\n  - id: CVE-2026-0001\n    statement: >-\n      first part\n      second part\n"
        '    owner: "someone"\n    expired_at: 2027-01-23\n'
    )
    assert parse_register(text) == [
        {"id": "CVE-2026-0001", "statement": "first part second part", "owner": "someone", "expired_at": "2027-01-23"}
    ]


@pytest.mark.parametrize(
    "text",
    [
        "- id: CVE-2026-0001\n",
        "vulnerabilities:\n    id: CVE-2026-0001\n",
        "vulnerabilities:\n  - id: CVE-2026-0001\n    id: CVE-2026-0002\n",
        "vulnerabilities:\n  - id: CVE-2026-0001\n  stray: line\n",
        "misconfigurations:\n  - id: AVD-1\n",
    ],
)
def test_a_register_the_parser_cannot_read_is_an_error_not_a_pass(text):
    with pytest.raises(ValueError):
        parse_register(text)


def test_an_empty_register_is_allowed():
    assert parse_register("vulnerabilities: []\n") == []


def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_trivy_is_pinned_by_tag_and_digest_never_by_tag_alone():
    pins = re.findall(r'(?m)^TRIVY_IMAGE="([^"]+)"', script())
    assert len(pins) == 1
    assert re.fullmatch(r"ghcr\.io/aquasecurity/trivy:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", pins[0]), pins[0]
    version = tuple(int(part) for part in pins[0].split(":")[1].split("@")[0].split("."))
    assert version >= (0, 72, 0), "0.72.0 or later carries the plugin path-traversal fix (see GHSA-69fq-xp46-6x23)"
    assert ":latest" not in script()


def test_the_scan_container_is_hardened_like_the_other_repositories():
    body = script()
    for flag in (
        "--rm",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--user ",
        "--tmpfs /tmp",
    ):
        assert flag in body, f"scan-image.sh lost {flag}"
    assert ':/scan:ro"' in body and ':/config/trivyignore.yaml:ro"' in body, (
        "the image and the register mount read-only"
    )
    for forbidden in ("docker.sock", "--privileged", "--network host", "--pid", "--cap-add"):
        assert forbidden not in body, forbidden


def test_the_gate_fails_on_fixable_high_and_critical_and_honours_the_register():
    body = script()
    assert 'SEVERITY="HIGH,CRITICAL"' in body
    gate = body.split("== pass 1", 1)[1].split("== pass 2", 1)[0]
    for flag in (
        "--ignore-unfixed",
        "--exit-code 1",
        "--ignorefile /config/trivyignore.yaml",
        '--severity "$SEVERITY"',
    ):
        assert flag in gate, f"the gate lost {flag}"
    assert 'exit "$gate"' in body
    register_check = body.split("== pass 2", 1)[1].split("unregistered=", 1)[0]
    assert "--ignore-unfixed" not in register_check, "the register check must see the unfixed findings"
    assert "--ignorefile /config/trivyignore.yaml" in register_check


def test_the_script_does_not_publish_or_push_anything():
    body = script()
    for forbidden in ("docker push", "docker login", "gh release", "git push"):
        assert forbidden not in body


def workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_the_scan_runs_weekly_and_by_hand():
    body = workflow()
    assert re.search(r'(?m)^  schedule: \[\{ cron: "\d{1,2} \d{1,2} \* \* [0-6]" \}\]$', body), "one weekly cron"
    assert re.search(r"(?m)^  workflow_dispatch:", body)
    assert "bash scripts/scan-image.sh" in body


def test_the_scan_cannot_be_made_to_pass_by_ignoring_its_result():
    body = workflow()
    assert "continue-on-error" not in body
    assert "|| true" not in body
    assert "pull_request_target" not in body


def test_the_scan_runs_when_the_base_image_pin_or_the_register_changes():
    body = workflow()
    for path in ("infrastructure/docker/**", ".trivyignore.yaml", "scripts/scan-image.sh", "requirements.lock.txt"):
        assert f'"{path}"' in body, f"a change to {path} should start the scan"
