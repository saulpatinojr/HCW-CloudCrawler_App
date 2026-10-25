"""Check that every place that names the release version agrees, before a tag can make a mistake permanent.

Why this exists: a `v*` tag cannot be moved or deleted once it is pushed (the "Protect release tags" ruleset), so a
tag that disagrees with the package version is a permanent mistake, and a wheel whose file name says one version while
the code inside says another is worse. The check has two modes, both stdlib only.

* Without `--tag` (CI, every pull request, `make lint`): the version in the engine's `pyproject.toml`, the appliance's
  `pyproject.toml`, both `__version__` constants and both `uv.lock` entries must be the same plain `X.Y.Z`.
* With `--tag vX.Y.Z` (release.yml and publish-core.yml on a tag): the same, plus the tag must be `v` + that version,
  `CHANGELOG.md` must have a dated, non-empty `## [X.Y.Z] - YYYY-MM-DD` section and an empty `## [Unreleased]`
  section (so the release notes are complete), and, with `--ancestor-of REF`, the tagged commit must already be on
  that branch (only reviewed commits are released).

`--notes-out FILE` writes the changelog section for the version (the release notes). `--dist DIR` checks the built
files: exactly the wheel and the sdist, named for the version, and the wheel's own `__version__` equal to it.

Exit 0 when everything agrees, 1 with one line per problem otherwise (GitHub `::error::` annotations under Actions).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
HEADING = re.compile(r"^## \[(?P<name>[^\]]+)\](?: - (?P<date>\S+))?\s*$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DUNDER = re.compile(r'^__version__\s*=\s*"([^"]*)"\s*$', re.M)
ENGINE = "packages/cloud-crawler-core"
SOURCES = {
    "engine pyproject.toml": f"{ENGINE}/pyproject.toml",
    "appliance pyproject.toml": "pyproject.toml",
    "engine __version__": f"{ENGINE}/src/cloud_crawler_core/__init__.py",
    "appliance __version__": "src/cloud_crawler_appliance/__init__.py",
}
LOCKED = {"cloud-crawler-core": "engine uv.lock entry", "cloud-crawler-appliance": "appliance uv.lock entry"}


def read_versions(root: Path) -> tuple[dict[str, str], list[str]]:
    """Return {where: version} for every source that could be read, and a list of problems for those that could not."""
    found: dict[str, str] = {}
    problems: list[str] = []
    for label, relative in SOURCES.items():
        path = root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            problems.append(f"cannot read {relative} ({label}): {error.strerror or error}")
            continue
        if relative.endswith(".toml"):
            version = tomllib.loads(text).get("project", {}).get("version")
        else:
            match = DUNDER.search(text)
            version = match.group(1) if match else None
        if isinstance(version, str) and version:
            found[label] = version
        else:
            problems.append(f"no version found in {relative} ({label})")
    try:
        lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        problems.append(f"cannot read uv.lock: {error}")
        return found, problems
    packages = {p.get("name"): p.get("version") for p in lock.get("package", [])}
    for name, label in LOCKED.items():
        if packages.get(name):
            found[label] = packages[name]
        else:
            problems.append(f"uv.lock has no entry for {name} ({label})")
    return found, problems


def changelog_sections(text: str) -> dict[str, tuple[str | None, str]]:
    """Map each `## [name]` heading to (date, body). Headings inside code fences are ignored."""
    sections: dict[str, tuple[str | None, list[str]]] = {}
    current: list[str] | None = None
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        match = None if fenced else HEADING.match(line)
        if match:
            current = []
            sections[match.group("name")] = (match.group("date"), current)
        elif not fenced and line.startswith("## "):
            current = None
        elif current is not None:
            current.append(line)
    return {name: (date, "\n".join(body).strip("\n")) for name, (date, body) in sections.items()}


def has_content(body: str) -> bool:
    """True when a section holds more than empty sub-headings (`### Fixed` with nothing under it is not content)."""
    return any(line.strip() and not line.startswith("#") for line in body.splitlines())


def check_dist(dist: Path, version: str) -> list[str]:
    problems: list[str] = []
    wheel_name = f"cloud_crawler_core-{version}-py3-none-any.whl"
    expected = {wheel_name, f"cloud_crawler_core-{version}.tar.gz"}
    present = {p.name for p in dist.glob("*")} if dist.is_dir() else set()
    for name in sorted(expected - present):
        problems.append(f"{dist}/{name} is missing: the build did not produce the version {version}")
    for name in sorted(present - expected):
        problems.append(f"{dist}/{name} is not expected: only the wheel and the sdist for {version} may be released")
    if wheel_name in present:
        with zipfile.ZipFile(dist / wheel_name) as archive:
            member = next((n for n in archive.namelist() if n == "cloud_crawler_core/__init__.py"), None)
            match = DUNDER.search(archive.read(member).decode("utf-8")) if member else None
        if not match or match.group(1) != version:
            inside = match.group(1) if match else "none"
            problems.append(f"the wheel's own __version__ is {inside}, the file name says {version}")
    return problems


def on_branch(sha: str, ref: str, root: Path) -> str | None:
    """None when `sha` is an ancestor of `ref`, otherwise the reason it is not."""
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, ref], cwd=root, capture_output=True, text=True, check=False
    )
    if result.returncode == 0:
        return None
    if result.returncode == 1:
        return f"commit {sha[:12]} is not on {ref}: release only commits that reached the protected branch"
    return f"could not compare {sha[:12]} with {ref}: {result.stderr.strip() or 'git failed'}"


def check(root: Path, tag: str | None = None, dist: Path | None = None) -> tuple[list[str], str | None]:
    """Return (problems, version). `version` is None when the sources disagree so much that none can be trusted."""
    versions, problems = read_versions(root)
    distinct = sorted(set(versions.values()))
    if len(distinct) > 1:
        for label, version in versions.items():
            problems.append(f"{label} says {version}")
        problems.insert(0, f"the version differs between files ({', '.join(distinct)})")
    version = distinct[0] if len(distinct) == 1 else None
    if version is not None and not VERSION.match(version):
        problems.append(f"version {version!r} is not a plain X.Y.Z (pre-release tags are not supported here)")
        version = None
    if tag is not None:
        tag = tag.removeprefix("refs/tags/")
        if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
            problems.append(f"tag {tag!r} is not v followed by X.Y.Z")
        elif version is not None and tag != f"v{version}":
            problems.append(f"tag {tag} does not match the package version {version}")
    if version is not None and tag is not None:
        try:
            sections = changelog_sections((root / "CHANGELOG.md").read_text(encoding="utf-8"))
        except OSError as error:
            problems.append(f"cannot read CHANGELOG.md: {error.strerror or error}")
            sections = {}
        date, body = sections.get(version, (None, ""))
        if version not in sections:
            problems.append(f"CHANGELOG.md has no '## [{version}] - YYYY-MM-DD' section")
        elif not date or not DATE.match(date):
            problems.append(f"the CHANGELOG.md section for {version} has no release date (found {date!r})")
        elif not has_content(body):
            problems.append(f"the CHANGELOG.md section for {version} is empty")
        if "Unreleased" in sections and has_content(sections["Unreleased"][1]):
            problems.append("CHANGELOG.md still has entries under [Unreleased]: fold them into the release section")
    if dist is not None and version is not None:
        problems.extend(check_dist(dist, version))
    return problems, version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--tag", help="the tag being released, for example v0.1.0 (refs/tags/ prefix allowed)")
    parser.add_argument("--dist", type=Path, help="directory holding the built wheel and sdist")
    parser.add_argument("--notes-out", type=Path, help="write the changelog section for the version to this file")
    parser.add_argument("--ancestor-of", metavar="REF", help="with --tag: the tagged commit must be reachable from REF")
    args = parser.parse_args(argv)
    problems, version = check(args.root, args.tag, args.dist)
    if args.tag and args.ancestor_of and version:
        sha = (
            os.environ.get("GITHUB_SHA")
            or subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=args.root, capture_output=True, text=True, check=False
            ).stdout.strip()
        )
        reason = on_branch(sha, args.ancestor_of, args.root)
        if reason:
            problems.append(reason)
    if args.notes_out and version:
        sections = changelog_sections((args.root / "CHANGELOG.md").read_text(encoding="utf-8"))
        body = sections.get(version, (None, ""))[1]
        if has_content(body):
            args.notes_out.write_text(body + "\n", encoding="utf-8")
        elif not any("CHANGELOG.md" in p for p in problems):
            problems.append(f"the CHANGELOG.md section for {version} is missing or empty: there are no release notes")
    github = os.environ.get("GITHUB_ACTIONS") == "true"
    if args.notes_out and not args.tag and version:
        sections = changelog_sections((args.root / "CHANGELOG.md").read_text(encoding="utf-8"))
        if "Unreleased" in sections and has_content(sections["Unreleased"][1]):
            warning = (
                "CHANGELOG.md still has entries under [Unreleased]; a real tag is refused until they are folded in"
            )
            print(f"::warning::{warning}" if github else f"warning: {warning}")
    for problem in problems:
        print(f"::error::{problem}" if github else f"error: {problem}")
    if problems:
        return 1
    tagged = f", tag {args.tag.removeprefix('refs/tags/')}" if args.tag else ""
    print(f"release version consistent: {version}{tagged}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
