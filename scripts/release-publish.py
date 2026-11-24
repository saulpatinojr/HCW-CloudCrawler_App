"""The steps of publish-core.yml that decide what a release holds, kept here so that tests can run them.

Why this exists: a `v*` tag cannot be moved or deleted once it is pushed, so the steps that decide whether the files
are really the attested ones, and whether a release becomes public, must not be untested shell inside a workflow.
Stdlib only; it calls the GitHub CLI (`gh`), authenticated by `GH_TOKEN` in the workflow. Run it with `python -I`.

* `write-provenance`: copy the provenance that `actions/attest` just signed (its `bundle-path` output, a Sigstore
  bundle: the signed statement, the signing certificate and the public log entry) into the file the release
  attaches, `cloud_crawler_core-<version>.intoto.jsonl`, one bundle per line. It is written only when every bundle
  is a provenance statement that names the wheel and the sdist by their sha256.
* `verify-attestations`: for the wheel and the sdist in a directory, `gh attestation verify` the provenance and the
  CycloneDX SBOM, and insist that the attestation came from THIS workflow file, on THIS ref, at THIS commit. Without
  those three, "some attestation for this file exists in this repository" would be enough, and a dry-run attestation
  of the same bytes would satisfy a real release. With `--provenance-dir`, the provenance file is verified the same
  way (`--bundle`), so the file a release attaches is proven to work before anything is published.
* `publish`: create the GitHub Release as a DRAFT with the four files, re-read the draft by its id until the four
  files are `uploaded` (bounded), check that it holds exactly those files (names, upload state and, where GitHub
  reports one, the sha256; when it reports none, say so), and only then make it public. A release that
  already exists for the tag (draft or public) is never touched, and no file is ever replaced: the job stops and
  says what to delete by hand. Until the last step succeeds no release is visible to anyone but the repository's
  writers, so a failure never leaves a public empty release next to the permanent tag.

Exit 0 on success, 1 with one line per problem (GitHub `::error::` annotations under Actions).
"""

from __future__ import annotations

import argparse
import base64
import binascii
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
# the name OpenSSF Scorecard's Signed-Releases check reads as provenance; the file is JSON lines, one Sigstore bundle
# per line, and `gh attestation verify <file> --bundle <this file>` checks a download against it
PROVENANCE_SUFFIX = ".intoto.jsonl"
PROVENANCE_DIR = "provenance"
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


def dist_files(directory: Path) -> tuple[list[Path], str | None]:
    """(the wheel and the sdist in `directory`, or the reason it does not hold exactly those two)."""
    files = sorted([*directory.glob("*.whl"), *directory.glob("*.tar.gz")])
    if len(files) != 2 or {f.suffix for f in files} != {".whl", ".gz"}:
        return [], f"{directory} must hold exactly one wheel and one sdist to verify, found {[f.name for f in files]}"
    return files, None


def provenance_name(version: str) -> str:
    return f"cloud_crawler_core-{version}{PROVENANCE_SUFFIX}"


def version_of(files: list[Path]) -> str:
    """The version in the sdist's name (`cloud_crawler_core-<version>.tar.gz`)."""
    sdist = next(f for f in files if f.name.endswith(".tar.gz"))
    return sdist.name.removesuffix(".tar.gz").rpartition("-")[2]


def provenance_problems(text: str, files: list[Path]) -> tuple[list[dict], list[str]]:
    """(the bundles in `text`, what is wrong with them as the provenance of `files`).

    Nothing is trusted here that `gh attestation verify --bundle` does not check again with the signature; this is the
    offline part: the text is one or more Sigstore bundles, each a signed provenance statement, and between them they
    name every file by its sha256. It stops a file of the wrong kind (the SBOM attestation, an empty file, an error
    page) from being attached under the provenance name."""
    try:
        values = decode_json_values(text)
    except ValueError as error:
        return [], [f"the provenance is not JSON: {error}"]
    if not values:
        return [], ["the provenance is empty"]
    bundles: list[dict] = []
    named: set[str] = set()
    for number, value in enumerate(values, start=1):
        envelope = value.get("dsseEnvelope") if isinstance(value, dict) else None
        if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), str):
            return [], [f"provenance bundle {number} is not a Sigstore bundle with a signed statement (dsseEnvelope)"]
        try:
            statement = json.loads(base64.b64decode(envelope["payload"], validate=True))
        except (ValueError, binascii.Error) as error:
            return [], [f"the statement in provenance bundle {number} cannot be read: {error}"]
        if not isinstance(statement, dict) or statement.get("predicateType") != PROVENANCE:
            kind = statement.get("predicateType") if isinstance(statement, dict) else None
            return [], [f"provenance bundle {number} is a {kind!r} statement, expected {PROVENANCE}"]
        for subject in statement.get("subject") or []:
            digest = subject.get("digest") if isinstance(subject, dict) else None
            if isinstance(digest, dict) and isinstance(digest.get("sha256"), str):
                named.add(digest["sha256"])
        bundles.append(value)
    missing = [f.name for f in files if sha256_of(f) not in named]
    if missing:
        return bundles, [f"the provenance does not name {', '.join(missing)} by its sha256"]
    return bundles, []


def write_provenance(bundle: Path, directory: Path, out_dir: Path) -> list[str]:
    """Write the attest step's bundle as `<out_dir>/cloud_crawler_core-<version>.intoto.jsonl`, one bundle a line."""
    files, reason = dist_files(directory)
    if reason:
        return [reason]
    if not bundle.is_file():
        return [f"the attest step left no bundle at {bundle} (its bundle-path output), so there is no provenance file"]
    bundles, problems = provenance_problems(bundle.read_bytes().decode("utf-8", errors="replace"), files)
    if problems:
        return problems
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / provenance_name(version_of(files))
    if target.exists():
        return [f"{target} already exists; a provenance file is never replaced"]
    lines = [json.dumps(b, separators=(",", ":"), ensure_ascii=False) for b in bundles]
    target.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    print(f"wrote {target}: {len(bundles)} provenance bundle(s) naming {', '.join(f.name for f in files)}")
    return []


def provenance_file(provenance_dir: Path, files: list[Path]) -> tuple[Path | None, list[str]]:
    """(the provenance file for `files` in `provenance_dir`, or why it is not usable): the one file, by its name."""
    expected = provenance_name(version_of(files))
    present = sorted(p.name for p in provenance_dir.iterdir()) if provenance_dir.is_dir() else []
    if present != [expected]:
        return None, [f"{provenance_dir} must hold exactly {expected} (the provenance file), found {present}"]
    path = provenance_dir / expected
    _, problems = provenance_problems(path.read_bytes().decode("utf-8", errors="replace"), files)
    return (None, [f"{expected}: {p}" for p in problems]) if problems else (path, [])


def verify_attestations(
    directory: Path,
    repo: str,
    workflow: str,
    source_ref: str,
    source_digest: str,
    provenance_dir: Path | None = None,
) -> list[str]:
    files, reason = dist_files(directory)
    if reason:
        return [reason]
    problems: list[str] = []
    if provenance_dir is not None:
        # the file the release attaches: checked from the file alone (`--bundle`), with the same strict flags. It is
        # not waited for, because nothing has to arrive: the proof is on disk
        bundle, problems = provenance_file(provenance_dir, files)
        for path in files if bundle else []:
            command = verify_command(path, repo, PROVENANCE, workflow, source_ref, source_digest)
            result = gh(*command, "--bundle", str(bundle))
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip().splitlines()
                problems.append(
                    f"{bundle.name} does not verify {path.name} as built by {workflow} on {source_ref} at "
                    f"{source_digest[:12]}: {detail[-1] if detail else 'gh failed'}"
                )
            else:
                print(f"verified {path.name} against the file {bundle.name}")
        if problems:
            return problems
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
        provenance_name(version): directory / PROVENANCE_DIR / provenance_name(version),
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
        wrong.append(f"asset {name} is on the release but is not one of the four expected files")
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
    """Re-read the draft by its id until its four files are `uploaded` (at most SETTLE_TRIES reads).

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
    dist = [path for name, path in expected.items() if name.endswith((".whl", ".tar.gz"))]
    _, problems = provenance_file(directory / PROVENANCE_DIR, dist)
    if problems:
        return [f"nothing was published: {problem}" for problem in problems]

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
    verify.add_argument(
        "--provenance-dir", type=Path, help="also verify the files against the .intoto.jsonl file in this directory"
    )
    write = commands.add_parser("write-provenance", help="write the attest step's bundle as the .intoto.jsonl file")
    write.add_argument("--bundle", type=Path, required=True, help="the attest step's bundle-path output")
    write.add_argument("--dir", type=Path, required=True, help="the directory holding the wheel and the sdist")
    write.add_argument("--out-dir", type=Path, required=True, help="where the .intoto.jsonl file is written")
    release = commands.add_parser("publish", help="create the release as a draft, check it, then make it public")
    release.add_argument("--tag", required=True)
    release.add_argument("--repo", required=True, help="owner/name")
    release.add_argument("--dir", type=Path, required=True, help="the downloaded release-files artifact")
    args = parser.parse_args(argv)
    if args.command == "verify-attestations":
        problems = verify_attestations(
            args.dir, args.repo, args.workflow, args.source_ref, args.source_digest, args.provenance_dir
        )
    elif args.command == "write-provenance":
        problems = write_provenance(args.bundle, args.dir, args.out_dir)
    else:
        problems = publish(args.repo, args.tag, args.dir)
    report(problems)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
