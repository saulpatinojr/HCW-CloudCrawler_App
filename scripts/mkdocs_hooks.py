"""MkDocs hook: the "Release notes" page is CHANGELOG.md, so the site and the repository never say two things.

CHANGELOG.md sits at the repository root, outside docs/, and its links are written for the repository ("docs/adr/..."
and "LICENSE"). `release_notes_page` turns it into a page of the site: it drops the note for contributors, writes a
title, and rewrites each relative link so it still works from the site (a link into docs/ points at the page, any other
repository file points at its GitHub page). The function is plain text in, text out, so tests can run it without
MkDocs installed; MkDocs imports are made only inside the hook.
"""

from __future__ import annotations

import re
from pathlib import Path

BLOB = "https://github.com/saulpatinojr/HCW-CloudCrawler_App/blob/main/"
TITLE = "# Release notes"
INTRO = (
    "These notes are the repository's `CHANGELOG.md`, shown here unchanged apart from the links. "
    "The version in each heading is the version of the engine package `cloud-crawler-core` and of the appliance. "
    "A heading with a date is a released version; entries under **Unreleased** are on `main` but not released yet. "
    'Nothing here means the appliance is ready for production: `GET /api/health` reports `"production": false`.\n'
)
LINK = re.compile(r"(\]\()([^)\s]+)((?:\s+\"[^\"]*\")?\))")


def rewrite_link(target: str) -> str:
    """Make one link target from CHANGELOG.md work from the site's root (where release-notes.md is served)."""
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith(("#", "/")):
        return target
    path, hash_mark, anchor = target.partition("#")
    path = path.removeprefix("./")
    if path.startswith("docs/") and path.endswith(".md"):
        return path.removeprefix("docs/") + hash_mark + anchor
    return BLOB + path + hash_mark + anchor


def release_notes_page(changelog: str) -> str:
    """The text of the Release notes page for the text of CHANGELOG.md."""
    start = re.search(r"(?m)^## ", changelog)
    body = changelog[start.start() :] if start else changelog
    body = LINK.sub(lambda m: m.group(1) + rewrite_link(m.group(2)) + m.group(3), body)
    return f"{TITLE}\n\n{INTRO}\n{body.rstrip()}\n"


def on_files(files, config):  # pragma: no cover - needs MkDocs; the text work is tested through release_notes_page
    from mkdocs.structure.files import File

    changelog = Path(config["config_file_path"]).parent / "CHANGELOG.md"
    page = release_notes_page(changelog.read_text(encoding="utf-8"))
    files.append(File.generated(config, "release-notes.md", content=page))
    return files
