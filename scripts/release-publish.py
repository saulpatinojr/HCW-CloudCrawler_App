"""The two steps of publish-core.yml that talk to GitHub about a release, kept here so that tests can run them.

Why this exists: a `v*` tag cannot be moved or deleted once it is pushed, so the steps that decide whether the files
are really the attested ones, and whether a release becomes public, must not be untested shell inside a workflow.
Stdlib only; it calls the GitHub CLI (`gh`), authenticated by `GH_TOKEN` in the workflow. Run it with `python -I`.

* `verify-attestations`: for the wheel and the sdist in a directory, `gh attestation verify` the provenance and the
  CycloneDX SBOM, and insist that the attestation came from THIS workflow file, on THIS ref, at THIS commit. Without
  those three, "some attestation for this file exists in this repository" would be enough, and a dry-run attestation
  of the same bytes would satisfy a real release.
* `publish`: create the GitHub Release as a DRAFT with the three files, re-read the draft by its id until the three
  files are `uploaded` (bounded), check that it holds exactly those files (names, upload state and, where GitHub
  reports one, the sha256; when it reports none, say so), and only then make it public. A release that
  already exists for the tag (draft or public) is never touched, and no file is ever replaced: the job stops and
  says what to delete by hand. Until the last step succeeds no release is visible to anyone but the repository's
  writers, so a failure never leaves a public empty release next to the permanent tag.

Exit 0 on success, 1 with one line per problem (GitHub `::error::` annotations under Actions).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess  # nosec B404 - only runs gh, with a fixed argument list and no shell
import sys
import time
from pathlib import Path

PROVENANCE = "https://slsa.dev/provenance/v1"
SBOM = "https://cyclonedx.org/bom"
SBOM_NAME = "cloud-crawler-core.cdx.json"
LOOKUP_TRIES = 10
LOOKUP_PAUSE_SECONDS = 3.0
# a draft that is listed can still show stale or missing assets, or assets in state `open` (GitHub's states are
# `uploaded` and `open`); it is re-read by id, at most SETTLE_TRIES times (about two minutes)
SETTLE_TRIES = 20
SETTLE_PAUSE_SECONDS = 6.0
# a new attestation can take a while to be readable. The waits between tries back off, and they share one budget for
# the whole step (about four minutes), so a wrong attestation cannot keep the job waiting four minutes per file.
VERIFY_DELAYS = (5.0, 10.0, 20.0, 30.0, 45.0, 60.0, 60.0)
VERIFY_BUDGET_SECONDS = sum(VERIFY_DELAYS)
GH_TIMEOUT_SECONDS = 300.0
WORKFLOWS_NOTE = (
    "GitHub refuses a token without workflow permission to create or change a release whose target commit modifies "
    ".github/workflows/ compared with the default branch (https://docs.github.com/en/rest/releases/releases), and "
    "answers 403 or 404 for it. If that is the cause, publish the release by hand from this run's files: README, "
    '"If a release goes wrong"'
)


def gh(*args: str) -> subprocess.CompletedProcess[str]:
    """Run gh; a call that hangs is cut off and reported as a failure, so the job cannot sit on a half-made release."""
    try:
        return subprocess.run(  # nosec B603 B607 - gh by name, arguments are a fixed list, no shell
            ["gh", *args], capture_output=True, text=True, check=False, timeout=GH_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            ["gh", *args], 124, "", f"gh {args[0]} did not answer within {GH_TIMEOUT_SECONDS:.0f} seconds"
        )


def sleep(seconds: float) -> None:
    time.sleep(seconds)


def report(problems: list[str]) -> None:
    github = os.environ.get("GITHUB_ACTIONS") == "true"
    for problem in problems:
        print(f"::error::{problem}" if github else f"error: {problem}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if problems and summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("### The release step stopped\n\n" + "".join(f"- {p}\n" for p in problems) + "\n")


def notice(message: str) -> None:
    print(f"::notice::{message}" if os.environ.get("GITHUB_ACTIONS") == "true" else f"notice: {message}")


def failure_help(repo: str, text: str) -> list[str]:
    """What to tell the owner after a failed GitHub call: nothing is public, how to clean up, the likely cause."""
    lines = [
        f"nothing was made public. A draft may be left behind: delete it on https://github.com/{repo}/releases "
        "(the tag stays) before re-running"
    ]
    if any(word in text.lower() for word in ("workflow", "403", "404", "not accessible", "forbidden")):
        lines.append(WORKFLOWS_NOTE)
    return lines


def verify_command(
    path: Path, repo: str, predicate: str, workflow: str, source_ref: str, source_digest: str
) -> list[str]:
    """The `gh attestation verify` arguments: the file, this repository, the predicate, and where it was built."""
    return [
        "attestation",
        "verify",
        str(path),
        "--repo",
        repo,
        "--predicate-type",
        predicate,
        "--signer-workflow",
        f"{repo}/{workflow}",
        "--source-ref",
        source_ref,
        "--source-digest",
        source_digest,
    ]


def verify_attestations(directory: Path, repo: str, workflow: str, source_ref: str, source_digest: str) -> list[str]:
    files = sorted([*directory.glob("*.whl"), *directory.glob("*.tar.gz")])
    if len(files) != 2 or {f.suffix for f in files} != {".whl", ".gz"}:
        return [f"{directory} must hold exactly one wheel and one sdist to verify, found {[f.name for f in files]}"]
    problems: list[str] = []
    budget = VERIFY_BUDGET_SECONDS
    for path in files:
        for predicate in (PROVENANCE, SBOM):
            command = verify_command(path, repo, predicate, workflow, source_ref, source_digest)
            result = gh(*command)
            for delay in VERIFY_DELAYS:
                if result.returncode == 0 or budget <= 0:
                    break
                pause = min(delay, budget)
                budget -= pause
                sleep(pause)
                result = gh(*command)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip().splitlines()
                problems.append(
                    f"no {predicate} attestation of {path.name} from {workflow} on {source_ref} at "
                    f"{source_digest[:12]}: {detail[-1] if detail else 'gh failed'}"
                )
            else:
                print(f"verified {predicate} for {path.name} ({workflow}, {source_ref}, {source_digest[:12]})")
    return problems


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_files(directory: Path, tag: str) -> dict[str, Path]:
    version = tag.removeprefix("v")
    wheel = f"cloud_crawler_core-{version}-py3-none-any.whl"
    sdist = f"cloud_crawler_core-{version}.tar.gz"
    return {
        wheel: directory / "dist" / wheel,
        sdist: directory / "dist" / sdist,
        SBOM_NAME: directory / "sbom" / SBOM_NAME,
    }


def decode_json_values(text: str) -> list[object]:
    """Every JSON value in `text`: `gh api --paginate` prints one array per page, back to back."""
    decoder = json.JSONDecoder()
    values: list[object] = []
    position = 0
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        value, position = decoder.raw_decode(text, position)
        values.append(value)
    return values


def releases_for_tag(repo: str, tag: str) -> tuple[list[dict], str | None]:
    """(the releases, drafts included, whose tag is `tag`, or the reason they could not be listed)."""
    result = gh("api", "--paginate", f"repos/{repo}/releases?per_page=100")
    if result.returncode != 0:
        return [], f"could not list the releases of {repo}: {(result.stderr or result.stdout).strip()}"
    try:
        pages = decode_json_values(result.stdout)
    except ValueError as error:
        return [], f"could not read the list of releases of {repo}: {error}"
    found = [
        r for page in pages if isinstance(page, list) for r in page if isinstance(r, dict) and r.get("tag_name") == tag
    ]
    return found, None


def assess(release: dict, expected: dict[str, Path], *, draft: bool) -> tuple[list[str], list[str]]:
    """(problems that may pass with time, problems that will not) for a release that should hold exactly `expected`.

    Time can fix a missing file or a file whose state is not yet `uploaded` (GitHub's other state is `open`); nothing
    but a new release fixes a wrong draft flag, a stray file or a digest that differs from the attested file."""
    waiting: list[str] = []
    wrong: list[str] = []
    if bool(release.get("draft")) is not draft:
        now, wanted = ("public", "a draft") if draft else ("still a draft", "public")
        wrong.append(f"the release is {now}, expected it to be {wanted}")
    assets = {a.get("name"): a for a in release.get("assets", []) if isinstance(a, dict)}
    for name in sorted(set(expected) - set(assets)):
        waiting.append(f"asset {name} is not on the release")
    for name in sorted(set(assets) - set(expected)):
        wrong.append(f"asset {name} is on the release but is not one of the three expected files")
    for name, asset in assets.items():
        if name not in expected:
            continue
        if asset.get("state") != "uploaded":
            waiting.append(f"asset {name} is in state {asset.get('state')!r}, not 'uploaded'")
        reported = asset.get("digest")
        if reported and reported != f"sha256:{sha256_of(expected[name])}":
            wrong.append(f"asset {name} on the release has digest {reported}, not the sha256 of the attested file")
    return waiting, wrong


def release_problems(release: dict, expected: dict[str, Path], *, draft: bool) -> list[str]:
    """Everything that is wrong with the release right now."""
    waiting, wrong = assess(release, expected, draft=draft)
    return [*wrong, *waiting]


def without_digest(release: dict, expected: dict[str, Path]) -> list[str]:
    """The expected files for which GitHub reports no sha256."""
    assets = {a.get("name"): a for a in release.get("assets", []) if isinstance(a, dict)}
    return sorted(name for name in expected if name in assets and not assets[name].get("digest"))


def get_release(repo: str, release_id: int) -> tuple[dict | None, str | None]:
    result = gh("api", f"repos/{repo}/releases/{release_id}")
    if result.returncode != 0:
        return None, f"could not read release {release_id}: {(result.stderr or result.stdout).strip()}"
    try:
        value = json.loads(result.stdout)
    except ValueError as error:
        return None, f"could not read release {release_id}: {error}"
    return (value, None) if isinstance(value, dict) else (None, f"release {release_id} did not come back as an object")


def settle_draft(repo: str, release_id: int, expected: dict[str, Path]) -> tuple[dict | None, list[str]]:
    """Re-read the draft by its id until its three files are `uploaded` (at most SETTLE_TRIES reads).

    The listing can show a draft before its files are complete, so the listing's copy is never trusted. A problem that
    time cannot fix (a stray file, a different digest) ends the wait at once."""
    release: dict | None = None
    problems: list[str] = []
    for attempt in range(SETTLE_TRIES):
        release, reason = get_release(repo, release_id)
        if release is None:
            problems = [reason or f"could not read release {release_id}"]
        else:
            waiting, wrong = assess(release, expected, draft=True)
            if wrong:
                return release, wrong
            if not waiting:
                return release, []
            problems = waiting
        if attempt + 1 < SETTLE_TRIES:
            sleep(SETTLE_PAUSE_SECONDS)
    return release, [f"after {SETTLE_TRIES} reads of the draft: {problem}" for problem in problems]


def publish(repo: str, tag: str, directory: Path) -> list[str]:
    expected = expected_files(directory, tag)
    notes = directory / "release-notes.md"
    missing = [str(p) for p in (notes, *expected.values()) if not p.is_file() or p.stat().st_size == 0]
    if missing:
        return [f"missing or empty, nothing was published: {', '.join(missing)}"]

    existing, reason = releases_for_tag(repo, tag)
    if reason:
        return [reason]
    if existing:
        kind = "a draft" if all(r.get("draft") for r in existing) else "a public release"
        return [
            f"{tag} already has {kind}. Nothing was changed: a file is never replaced. Delete that release on the "
            "Releases page (the tag stays) and re-run the failed jobs, or ship the next version"
        ]

    created = gh(
        "release", "create", tag, "--repo", repo, "--draft", "--verify-tag", "--title", tag,
        "--notes-file", str(notes), *map(str, expected.values()),
    )  # fmt: skip
    if created.returncode != 0:
        text = (created.stderr or created.stdout).strip()
        return [f"could not create the draft release {tag}: {text}", *failure_help(repo, text)]
    print(f"draft release for {tag} created with {len(expected)} files; checking it before it becomes public")

    draft: dict | None = None
    for attempt in range(LOOKUP_TRIES):
        found, reason = releases_for_tag(repo, tag)
        if reason is None and len(found) == 1:
            draft = found[0]
            break
        if reason is None and len(found) > 1:
            return [f"{len(found)} releases now exist for {tag}; leaving them as they are, nothing was made public"]
        if attempt + 1 < LOOKUP_TRIES:
            sleep(LOOKUP_PAUSE_SECONDS)
    if draft is None or not isinstance(draft.get("id"), int):
        return [f"the draft release for {tag} could not be found after it was created; nothing was made public"]

    release_id = draft["id"]
    settled, problems = settle_draft(repo, release_id, expected)
    if problems:
        return [*problems, *failure_help(repo, " ".join(problems))]
    missing_digest = without_digest(settled, expected) if settled else []
    if missing_digest:
        notice(
            f"GitHub reports no sha256 for {', '.join(missing_digest)}: the files are not compared with GitHub's own "
            "record, so their integrity rests on the sha256 list checked in this job and on the attestations"
        )

    made = gh("api", "--method", "PATCH", f"repos/{repo}/releases/{release_id}", "-F", "draft=false")
    if made.returncode != 0:
        text = (made.stderr or made.stdout).strip()
        return [f"could not make release {tag} public: {text}", *failure_help(repo, text)]
    final, reason = get_release(repo, release_id)
    if final is None:
        return [f"{reason}; the publish request was sent, so check the release page"]
    problems = release_problems(final, expected, draft=False)
    if final.get("tag_name") != tag:
        problems.append(f"the public release is for {final.get('tag_name')!r}, expected {tag!r}")
    if problems:
        return [*problems, "the release was made public but does not match: check the release page now"]
    print(f"release {tag} is public with {', '.join(sorted(expected))}: {final.get('html_url')}")
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser(
        "verify-attestations", help="verify the provenance and SBOM attestations of the dist files"
    )
    verify.add_argument("--dir", type=Path, required=True, help="the directory holding the wheel and the sdist")
    verify.add_argument("--repo", required=True, help="owner/name")
    verify.add_argument("--workflow", required=True, help="path of the workflow file that must have signed")
    verify.add_argument("--source-ref", required=True, help="the ref the attestation must name (refs/tags/vX.Y.Z)")
    verify.add_argument("--source-digest", required=True, help="the commit the attestation must name")
    release = commands.add_parser("publish", help="create the release as a draft, check it, then make it public")
    release.add_argument("--tag", required=True)
    release.add_argument("--repo", required=True, help="owner/name")
    release.add_argument("--dir", type=Path, required=True, help="the downloaded release-files artifact")
    args = parser.parse_args(argv)
    if args.command == "verify-attestations":
        problems = verify_attestations(args.dir, args.repo, args.workflow, args.source_ref, args.source_digest)
    else:
        problems = publish(args.repo, args.tag, args.dir)
    report(problems)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
