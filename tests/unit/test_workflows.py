"""The workflow set and the rules every workflow keeps, pinned as tests (no YAML library; the files share one style).

The release pipeline (publish-core.yml, one workflow that owns the whole sequence) first runs on the v0.1.0 tag, and a
v* tag can never be moved or deleted, so what it must and must not do is written down here: nothing is published
without a tag, a release becomes public only as the last step of one ordered path, the write permissions sit only where
they are used, no file is ever overwritten, and every step that guards the release is present. These are static checks
of the files; they do not prove how GitHub runs them."""

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
    "image-scan.yml",
    "publish-core.yml",
    "rehearse-self-merging-pr.yml",
    "repository-admin.yml",
    "security.yml",
}
TAG_ONLY = "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')"
PUBLISHING = ("gh release", "release-publish.py publish", "uv publish")
RELEASE_FILE = "publish-core.yml"
JOB_ORDER = ["build", "attest", "release", "pypi"]
SHA_CHECK = "sha256sum --check --strict SHA256SUMS"


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


def job_head(job: str) -> str:
    """The job's own lines before its steps: needs, if, runs-on and permissions."""
    return jobs(text(RELEASE_FILE))[job].split("    steps:")[0]


def job_steps(job: str) -> list[str]:
    return steps(jobs(text(RELEASE_FILE))[job])


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


def test_the_whole_release_is_one_workflow_with_one_ordered_path():
    body = text(RELEASE_FILE)
    assert list(jobs(body)) == JOB_ORDER
    assert re.search(r"(?m)^    needs: build$", job_head("attest"))
    assert re.search(r"(?m)^    needs: \[build, attest\]$", job_head("release"))
    assert re.search(r"(?m)^    needs: release$", job_head("pypi")), "PyPI only after the GitHub release is public"
    assert re.search(r'(?m)^  push:\n    tags: \["v\*"\]$', body)
    assert re.search(r"(?m)^  workflow_dispatch:", body), "no dry run"


def test_nothing_is_published_without_a_tag():
    for job in ("release", "pypi"):
        assert TAG_ONLY in job_head(job), f"the {job} job must only run for a pushed v* tag, never for a manual run"
    for job in ("build", "attest"):
        assert not any(command in "".join(job_steps(job)) for command in PUBLISHING), job
    assert "gh release create" not in text(RELEASE_FILE), "creating a release belongs to scripts/release-publish.py"
    assert "vars.PYPI_ENABLED == 'true'" in job_head("pypi")
    assert not (WORKFLOWS / "release.yml").exists(), "a second workflow would race this one for the same tag"


def test_a_dry_run_is_only_allowed_on_main_and_fails_at_once_elsewhere():
    first = job_steps("build")[0]
    assert "if: github.event_name != 'push' && github.ref != 'refs/heads/main'" in first
    assert "exit 1" in first and "::error::" in first
    inputs = text(RELEASE_FILE).split("\njobs:\n")[0].split("      attest:\n")[1]
    assert "default: false" in inputs and "type: boolean" in inputs, "the permanent signing log is opt-in"
    assert "inputs.attest" in job_head("attest") and "github.event_name == 'push'" in job_head("attest")


def test_the_dry_run_runs_the_same_checks_as_the_tag():
    build = "".join(job_steps("build"))
    assert build.count('if [ "$EVENT_NAME" = "push" ]; then mode=(--tag "$REF_NAME"); else mode=(--rehearse); fi') == 2
    assert 'check-release-version.py "${mode[@]}" --ancestor-of origin/main --notes-out release-notes.md' in build
    assert 'check-release-version.py "${mode[@]}" --dist dist' in build
    assert "fetch-depth: 0" in build
    assert "REF_TYPE" not in text(RELEASE_FILE), "tag or dry run is decided by the event, not by the ref type"
    assert "so the checks that need one are skipped" not in text(RELEASE_FILE)


def test_write_permissions_are_held_only_where_they_are_used():
    def grants(job: str) -> set[str]:
        block = re.search(r"(?ms)^    permissions:\n((?:      .*\n)+)", job_head(job) + "\n")
        return set(re.findall(r"(?m)^      ([a-z-]+: (?:read|write))(?: #.*)?$", block.group(1))) if block else set()

    assert grants("build") == set(), "building needs only the top-level contents: read"
    assert grants("attest") == {"contents: read", "id-token: write", "attestations: write"}
    assert grants("release") == {"contents: write", "attestations: read"}
    assert grants("pypi") == {"contents: read", "id-token: write"}
    body = text(RELEASE_FILE)
    assert len(re.findall(r"(?m)^\s+contents: write(?: #.*)?$", body)) == 1
    assert len(re.findall(r"(?m)^\s+id-token: write(?: #.*)?$", body)) == 2


def test_attestations_use_actions_attest_and_not_its_deprecated_wrapper():
    assert "attest-build-provenance" not in text(RELEASE_FILE)
    attest = [s for s in job_steps("attest") if "actions/attest@" in s]
    assert len(attest) == 2
    assert "sbom-path" not in attest[0] and "sbom-path:" in attest[1], "provenance first, then the SBOM"
    assert all("release-files/dist/*" in s for s in attest)


def test_every_release_job_has_a_time_limit():
    for job in JOB_ORDER:
        assert re.search(r"(?m)^    timeout-minutes: \d+$", job_head(job)), (
            f"{job} could hang for the default six hours"
        )


def test_the_release_is_serialised_per_ref_and_never_cancelled():
    head = text(RELEASE_FILE).split("\njobs:\n")[0]
    assert re.search(
        r"(?m)^concurrency:\n  group: publish-core-\$\{\{ github.ref \}\}\n  cancel-in-progress: false$", head
    )


def test_the_files_are_checked_against_the_build_wherever_they_are_downloaded():
    for job in ("attest", "release", "pypi"):
        listed = job_steps(job)
        download = next(n for n, s in enumerate(listed) if "actions/download-artifact@" in s)
        check = next(n for n, s in enumerate(listed) if SHA_CHECK in s)
        assert download < check, job
    build = "".join(job_steps("build"))
    assert "sha256sum dist/* sbom/* | tee SHA256SUMS" in build
    uploaded = build.split("upload-artifact")[1]
    for needle in ("dist\n", "sbom\n", "release-notes.md\n", "SHA256SUMS\n"):
        assert needle in uploaded


def test_the_dry_run_still_builds_and_checks_everything_the_tag_does():
    build = "".join(job_steps("build"))
    for needle in ("uv build", "verify-core-wheel.py", "cyclonedx1.5", "upload-artifact", "--dist dist", "--rehearse"):
        assert needle in build, needle


def test_the_wheel_verifier_needs_no_download_in_the_privileged_job():
    publish = text(RELEASE_FILE)
    assert "--with pydantic" not in publish, "verify-core-wheel.py imports only the standard library"
    assert "--no-create-gitignore" in publish, "dist/.gitignore would become an attested subject"
    assert '"uv==0.11.32"' in publish, "the flag was checked against uv 0.11.32 (VALIDATION.md)"


def test_the_attestations_are_verified_strictly_in_the_attest_job_and_again_before_publishing():
    for job in ("attest", "release"):
        verify = next(s for s in job_steps(job) if "verify-attestations" in s)
        assert 'SOURCE_REF: "${{ github.ref }}"' in verify and 'SOURCE_DIGEST: "${{ github.sha }}"' in verify
        assert 'WORKFLOW_FILE: ".github/workflows/publish-core.yml"' in verify
        for flag in ('--workflow "$WORKFLOW_FILE"', '--source-ref "$SOURCE_REF"', '--source-digest "$SOURCE_DIGEST"'):
            assert flag in verify, f"{job}: {flag}"
        assert "--dir release-files/dist" in verify


def test_a_release_becomes_public_only_after_download_check_verify_and_the_draft_checks():
    body = job_steps("release")
    markers = ("actions/download-artifact@", SHA_CHECK, "verify-attestations", "release-publish.py publish")
    order = [next(n for n, step in enumerate(body) if marker in step) for marker in markers]
    assert order == sorted(order) and len(set(order)) == 4, "download, sha256, verify the attestations, then publish"
    assert order[-1] == len(body) - 1, "publishing is the last step of the release job"
    assert '--tag "$TAG"' in body[-1] and "--dir release-files" in body[-1]


def test_the_version_guard_runs_everywhere_it_should():
    guard = "scripts/check-release-version.py"
    assert guard in text("ci.yml"), "pull requests must run the guard"
    assert guard in text(RELEASE_FILE)
    assert (ROOT / guard).is_file() and (ROOT / "scripts" / "release-publish.py").is_file()
