"""Check, before the owner pushes a release tag, that the commit about to be tagged is the one that was rehearsed.

Why this exists: a `v*` tag cannot be moved or deleted, and the workflow that runs for a tag is the copy stored IN THE
TAGGED COMMIT. A tag on an older commit (from before the release checks existed, or before a fix to them) would run that
older, unguarded workflow, and nothing inside a workflow can notice. So the check has to happen before the tag
is pushed.

It fails (exit 1, one line per problem) unless all of this holds:

* `--sha` is a full 40-character commit id that exists in this clone;
* that commit is the tip of `origin/main`, or an ancestor of it with `.github` and `scripts` identical to the tip
  (so the release machinery is the current one);
* a dry run of publish-core.yml on `main` succeeded on exactly that commit, with the `build` AND the `attest` jobs
  green (the dry run ticked "attest"; without it the attestation steps were never exercised);
* when `--tag` is given, no tag of that name exists in this clone.

Run it from a clone after `git fetch origin`, with the GitHub CLI signed in. It changes nothing. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404 - only runs git and gh, with fixed argument lists and no shell
import sys
from pathlib import Path

REPO = "saulpatinojr/HCW-CloudCrawler_App"
WORKFLOW = "publish-core.yml"
GATED_PATHS = (".github", "scripts")
REQUIRED_JOBS = ("build", "attest")
TIMEOUT_SECONDS = 120.0


def _run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # nosec B603 B607 - git/gh by name, fixed argument list, no shell
            command, cwd=cwd, capture_output=True, text=True, check=False, timeout=TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "", f"{command[0]} did not answer in {TIMEOUT_SECONDS:.0f}s")


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=root)


def gh(*args: str) -> subprocess.CompletedProcess[str]:
    return _run(["gh", *args])


def commit_of(root: Path, name: str) -> tuple[str | None, str]:
    result = git(root, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")
    return (result.stdout.strip() or None) if result.returncode == 0 else None, result.stderr.strip()


def commit_problems(root: Path, sha: str, main: str) -> tuple[list[str], list[str]]:
    """(problems, notes) about `sha` versus the tip of `main`."""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return [f"--sha must be a full 40-character commit id (lower case), not {sha!r}"], []
    found, _ = commit_of(root, sha)
    if found != sha:
        return [f"commit {sha[:12]} is not in this clone: run `git fetch origin` first"], []
    tip, _ = commit_of(root, main)
    if tip is None:
        return [f"{main} is not known here: run `git fetch origin` first"], []
    if sha == tip:
        return [], [f"{sha[:12]} is the tip of {main}"]
    ancestor = git(root, "merge-base", "--is-ancestor", sha, tip)
    if ancestor.returncode == 1:
        return [f"commit {sha[:12]} is not on {main}: tag only commits that reached the protected branch"], []
    if ancestor.returncode != 0:
        return [f"could not compare {sha[:12]} with {main}: {ancestor.stderr.strip() or 'git failed'}"], []
    same = git(root, "diff", "--quiet", sha, tip, "--", *GATED_PATHS)
    if same.returncode == 0:
        return [], [f"{main} has moved on ({tip[:12]}), but {' and '.join(GATED_PATHS)} are identical at {sha[:12]}"]
    if same.returncode == 1:
        return [
            f"{sha[:12]} is older than the tip of {main} ({tip[:12]}) and {' or '.join(GATED_PATHS)} differ: "
            "a tag here "
            "would run THAT commit's older release workflow, without the checks added since. Tag the tip of main, "
            "after a new dry run"
        ], []
    return [f"could not compare {GATED_PATHS} at {sha[:12]} and {tip[:12]}: {same.stderr.strip() or 'git failed'}"], []


def dry_run_problems(repo: str, sha: str, workflow: str) -> tuple[list[str], list[str]]:
    """(problems, notes): a successful dry run on `sha` in which the build and attest jobs both succeeded."""
    listed = gh(
        "run", "list", "--repo", repo, "--workflow", workflow, "--event", "workflow_dispatch", "--branch", "main",
        "--status", "success", "--limit", "50", "--json", "databaseId,headSha",
    )  # fmt: skip
    if listed.returncode != 0:
        return [f"could not list the dry runs: {(listed.stderr or listed.stdout).strip()}"], []
    try:
        runs = json.loads(listed.stdout)
    except ValueError as error:
        return [f"could not read the list of dry runs: {error}"], []
    mine = [r for r in runs if isinstance(r, dict) and r.get("headSha") == sha and isinstance(r.get("databaseId"), int)]
    if not mine:
        return [
            f"no successful dry run of {workflow} on main built {sha[:12]}: run it with -f attest=true, "
            "wait for green, "
            "and do not let main move before you tag"
        ], []
    reasons: list[str] = []
    for run in mine:
        viewed = gh("run", "view", str(run["databaseId"]), "--repo", repo, "--json", "jobs")
        if viewed.returncode != 0:
            reasons.append(
                f"run {run['databaseId']}: could not read its jobs: {(viewed.stderr or viewed.stdout).strip()}"
            )
            continue
        try:
            jobs = {j.get("name"): j.get("conclusion") for j in json.loads(viewed.stdout).get("jobs", [])}
        except (ValueError, AttributeError) as error:
            reasons.append(f"run {run['databaseId']}: could not read its jobs: {error}")
            continue
        bad = [f"{name} was {jobs.get(name) or 'not run'}" for name in REQUIRED_JOBS if jobs.get(name) != "success"]
        if not bad:
            return [], [
                f"dry run https://github.com/{repo}/actions/runs/{run['databaseId']} built {sha[:12]}: "
                "build and attest green"
            ]
        reasons.append(f"run {run['databaseId']}: {', '.join(bad)}")
    return [
        f"the dry run(s) on {sha[:12]} did not exercise the attestations ({'; '.join(reasons)}): run it again with "
        "-f attest=true and wait for build and attest to be green"
    ], []


def tag_problems(root: Path, tag: str) -> list[str]:
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        return [f"tag {tag!r} is not v followed by X.Y.Z"]
    existing = git(root, "rev-parse", "--quiet", "--verify", f"refs/tags/{tag}")
    if existing.returncode == 0:
        return [f"the tag {tag} already exists in this clone"]
    if existing.returncode != 1:
        return [f"could not look up the tag {tag}: {existing.stderr.strip() or 'git failed'}"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sha", required=True, help="the full commit id you are about to tag")
    parser.add_argument("--tag", help="the tag you are about to create, for example v0.1.0")
    parser.add_argument("--repo", default=REPO, help="owner/name (default %(default)s)")
    parser.add_argument("--main", default="origin/main", help="the protected branch as this clone knows it")
    parser.add_argument("--workflow", default=WORKFLOW, help="the release workflow file name")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    problems: list[str] = []
    notes: list[str] = []
    found, more = commit_problems(args.root, args.sha, args.main)
    problems += found
    notes += more
    if re.fullmatch(r"[0-9a-f]{40}", args.sha):  # a malformed id has been reported; do not ask GitHub about it
        found, more = dry_run_problems(args.repo, args.sha, args.workflow)
        problems += found
        notes += more
    if args.tag:
        problems += tag_problems(args.root, args.tag)
    for note in notes:
        print(f"ok: {note}")
    for problem in problems:
        print(f"error: {problem}")
    if problems:
        print("NOT safe to tag: fix the above, then run this check again")
        return 1
    print(
        f"safe to tag: git tag -a {args.tag or '<tag>'} {args.sha} -m <message>, "
        f"then git push origin {args.tag or '<tag>'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
