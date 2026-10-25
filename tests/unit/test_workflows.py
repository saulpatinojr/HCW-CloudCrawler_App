"""The workflow set and the rules every workflow keeps, pinned as tests (no YAML library; the files share one style).

The release pipeline (release.yml, publish-core.yml) first runs on the v0.1.0 tag, and a v* tag can never be moved or
deleted, so what it must and must not do is written down here: nothing is published without a tag, the write
permissions sit only where they are used, no file is ever overwritten, and every step that guards the release is
present. These are static checks of the files; they do not prove how GitHub runs them."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
EXPECTED = {
    "ci.yml",
    "codeql.yml",
    "dependency-review.yml",
    "publish-core.yml",
    "rehearse-self-merging-pr.yml",
    "release.yml",
    "repository-admin.yml",
    "security.yml",
}
TAG_ONLY = "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')"
PUBLISHING = ("gh release create", "gh release upload", "uv publish")


def text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def steps(body: str) -> list[str]:
    """Split a workflow into its steps: a step starts at six spaces and a dash."""
    parts = re.split(r"(?m)^(?=      - )", body)
    return [p for p in parts[1:]]


def jobs(body: str) -> dict[str, str]:
    """Map job name to its text: a job starts at two spaces and a name inside the top-level `jobs:` block."""
    _, _, rest = body.partition("\njobs:\n")
    pieces = re.split(r"(?m)^(?=  [A-Za-z0-9_-]+:\s*$)", rest)
    return {p.split(":", 1)[0].strip(): p for p in pieces if p.strip()}


def test_the_workflow_set_is_the_expected_one():
    assert {p.name for p in WORKFLOWS.glob("*.yml")} == EXPECTED, "add or remove the file here when the set changes"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_actions_are_pinned_to_a_full_sha_with_a_version_comment(name):
    uses = re.findall(r"(?m)^\s*(?:- )?uses:\s*(\S+)(.*)$", text(name))
    for target, rest in uses:
        if target.startswith("./"):
            continue
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", target), f"{name}: {target} is not pinned to a commit"
        assert re.search(r"#\s*v\d+(\.\d+){0,2}\b", rest), f"{name}: {target} has no version comment"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_runner_and_default_permissions(name):
    body = text(name)
    assert not re.search(r"(?m)^[^#\n]*(ubuntu-latest|pull_request_target)", body)  # comments may name them
    assert set(re.findall(r"(?m)^\s*runs-on:\s*(\S+)", body)) <= {"ubuntu-26.04"}
    head = body.partition("\njobs:\n")[0]
    assert re.search(r"(?m)^permissions:\n  contents: read$", head), (
        f"{name}: top-level permissions are not contents: read"
    )
    assert "persist-credentials: true" not in body


def test_nothing_overwrites_a_published_file():
    for name in EXPECTED:
        assert "--clobber" not in text(name), name


def test_the_coverage_gate_is_named_for_what_it_enforces():
    gate = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["coverage"]["report"][
        "fail_under"
    ]
    ci = text("ci.yml")
    assert f"--cov-fail-under={gate}" in ci
    assert f"with the {gate} percent coverage gate" in ci
    assert not re.search(r"\b85 percent\b", ci)


def test_both_release_workflows_run_on_v_tags_and_can_be_dry_run():
    for name in ("release.yml", "publish-core.yml"):
        body = text(name)
        assert re.search(r'(?m)^  push:\n    tags: \["v\*"\]$', body), name
        assert re.search(r"(?m)^  workflow_dispatch:", body), f"{name} has no dry run"


def test_nothing_is_published_without_a_tag():
    release = jobs(text("release.yml"))
    assert TAG_ONLY in release["create"].split("steps:")[0], (
        "the create job must only run for a pushed v* tag, never for a manual run"
    )
    assert "gh release create" not in release["check"]
    publish = text("publish-core.yml")
    for step in steps(publish):
        if any(command in step for command in PUBLISHING):
            assert TAG_ONLY in step, f"a publishing step runs without a tag:\n{step}"


def test_the_dry_run_of_publish_core_still_builds_and_attests_but_never_attaches():
    publish = text("publish-core.yml")
    for needle in ("uv build", "verify-core-wheel.py", "cyclonedx1.5", "upload-artifact", "attest-build-provenance"):
        assert needle in publish
    assert "inputs.attest" in publish
    attest = [s for s in steps(publish) if "actions/attest" in s]
    assert len(attest) == 2 and all("if: github.event_name == 'push' || inputs.attest" in s for s in attest)


def test_write_permissions_are_held_only_where_they_are_used():
    release = jobs(text("release.yml"))
    assert "contents: write" not in release["check"]
    assert "contents: write" in release["create"]
    assert "id-token" not in text("release.yml") and "attestations" not in text("release.yml")


def test_the_version_guard_runs_everywhere_it_should():
    guard = "scripts/check-release-version.py"
    assert guard in text("ci.yml"), "pull requests must run the guard"
    release, publish = text("release.yml"), text("publish-core.yml")
    for body in (release, publish):
        assert "--tag" in body and "--ancestor-of origin/main" in body and "fetch-depth: 0" in body
        assert guard in body
    assert "--notes-out" in release and "args=(--dist dist)" in publish
    assert "args+=(--tag" in publish
    assert (ROOT / guard).is_file()


def test_the_wheel_verifier_needs_no_download_in_the_privileged_job():
    publish = text("publish-core.yml")
    assert "--with pydantic" not in publish, "verify-core-wheel.py imports only the standard library"
    assert "--no-create-gitignore" in publish, "dist/.gitignore would become an attested subject"


def test_every_release_file_is_attached_and_checked_by_name():
    publish = text("publish-core.yml")
    attach = next(s for s in steps(publish) if "gh release upload" in s)
    assert 'wheel="cloud_crawler_core-${version}-py3-none-any.whl"' in attach
    assert 'sdist="cloud_crawler_core-${version}.tar.gz"' in attach
    assert 'sbom="cloud-crawler-core.cdx.json"' in attach
    assert "gh release view" in attach and "did not appear" in attach
    assert "dist/*" not in attach


def test_the_release_step_reports_lookup_failures_instead_of_creating_blindly():
    create = jobs(text("release.yml"))["create"]
    assert "--verify-tag" in create and "release not found" in create and "--notes-file release-notes.md" in create
    assert "See CHANGELOG.md for" not in text("release.yml"), "a missing changelog section must fail, not fall back"


def test_attestations_are_verified_before_anything_is_attached_or_published():
    body = steps(text("publish-core.yml"))
    markers = ("actions/attest@", "gh attestation verify", "gh release upload", "uv publish")
    order = [next(n for n, step in enumerate(body) if marker in step) for marker in markers]
    assert order == sorted(order) and len(set(order)) == 4, "attest, then verify, then attach, then PyPI"
