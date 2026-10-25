"""The documentation site (GitHub Pages, ticket #11): its build files, the release-notes hook and the link checker.

These are static checks and unit tests; they do not build the site (CI's `docs` workflow does, with MkDocs, which is
in the separate `docs` dependency group and is not installed for the test run)."""

from __future__ import annotations

import importlib.util
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hooks = _load("mkdocs_hooks", "mkdocs_hooks.py")
links = _load("check_site_links", "check-site-links.py")


# --- the release-notes hook ---------------------------------------------------------------------------------------

CHANGELOG = """# Changelog

Add an entry under **Unreleased** in the same pull request as the change.

## [Unreleased]

## [0.1.0] - 2026-10-25

See [the decision](docs/adr/0004-x.md#owner-decisions) and [the licence](LICENSE),
[the sign-in](docs/adr/0004-x.md "t"), [a pull request](https://github.com/o/r/pull/2), [a heading](#added),
[a script](./scripts/a.py) and [a folder](docs/).
"""


def test_the_release_notes_page_starts_at_the_first_version_heading_and_has_a_title():
    page = hooks.release_notes_page(CHANGELOG)
    assert page.startswith("# Release notes\n")
    assert "Add an entry under" not in page
    assert page.index("## [Unreleased]") < page.index("## [0.1.0] - 2026-10-25")
    assert '"production": false' in page, "the page must not read as a production claim"


def test_links_into_docs_become_page_links_and_other_repository_files_become_github_links():
    page = hooks.release_notes_page(CHANGELOG)
    assert "(adr/0004-x.md#owner-decisions)" in page
    assert '(adr/0004-x.md "t")' in page
    assert f"({hooks.BLOB}LICENSE)" in page
    assert f"({hooks.BLOB}scripts/a.py)" in page
    assert f"({hooks.BLOB}docs/)" in page, "a folder is not a page of the site"


def test_outside_and_in_page_links_are_left_alone():
    page = hooks.release_notes_page(CHANGELOG)
    assert "(https://github.com/o/r/pull/2)" in page
    assert "(#added)" in page


def test_a_changelog_with_no_version_heading_is_kept_whole():
    assert "just text" in hooks.release_notes_page("just text\n")


def test_the_real_changelog_turns_into_a_page_whose_docs_links_name_files_that_exist():
    page = hooks.release_notes_page((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    for target in re.findall(r"\]\(([^)\s#]+\.md)", page):
        assert (DOCS / target).exists(), target
    assert "](docs/" not in page


# --- the link checker ---------------------------------------------------------------------------------------------

PAGE = '<!doctype html><html><head><meta name="viewport" content="width=device-width"></head><body>{body}</body></html>'


def site(directory: Path, pages: dict[str, str]) -> Path:
    for name, body in pages.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PAGE.format(body=body), encoding="utf-8")
    return directory


def problems(directory: Path, pages: dict[str, str]) -> list[str]:
    return links.check(site(directory, pages))[0]


def test_a_sound_site_has_no_problems(tmp_path):
    pages = {
        "index.html": '<a href="a/">A</a> <a href="a/#top">top</a> <a href="https://example.invalid/">out</a>',
        "a/index.html": '<h1 id="top">A</h1><a href="../">home</a><a href="../b.html">B</a>',
        "b.html": '<a href="#x">x</a><p id="x"></p>',
    }
    assert links.check(site(tmp_path, pages)) == ([], 3, 1)


def test_a_link_to_a_missing_page_is_reported(tmp_path):
    found = problems(tmp_path, {"index.html": '<a href="gone/">x</a>'})
    assert len(found) == 1 and "gone/" in found[0]


def test_a_link_to_a_missing_heading_is_reported(tmp_path):
    found = problems(tmp_path, {"index.html": '<a href="a/#nope">x</a>', "a/index.html": '<h1 id="yes"></h1>'})
    assert len(found) == 1 and "#nope" in found[0]


def test_a_page_without_the_viewport_tag_is_reported(tmp_path):
    (tmp_path / "index.html").write_text("<html><body>hello</body></html>", encoding="utf-8")
    assert links.check(tmp_path)[0] == ["index.html: no viewport meta tag"]


def test_a_page_no_link_reaches_is_reported(tmp_path):
    found = problems(tmp_path, {"index.html": "<p>alone</p>", "orphan/index.html": "<p>lost</p>"})
    assert found == ["orphan/index.html: no link path from the home page reaches it"]


def test_a_link_that_leaves_the_site_is_reported(tmp_path):
    found = problems(tmp_path / "inner", {"index.html": '<a href="../x.html">x</a>'})
    assert len(found) == 1 and "../x.html" in found[0]


def test_an_empty_folder_is_a_problem_not_a_pass(tmp_path):
    assert "build the site first" in links.check(tmp_path)[0][0]


def test_the_404_page_is_not_link_checked(tmp_path):
    pages = {"index.html": "<p>home</p>", "404.html": '<link href="/base/css/x.css" rel="stylesheet">'}
    assert problems(tmp_path, pages) == []


def test_the_command_line_exit_codes(tmp_path, capsys):
    site(tmp_path, {"index.html": "<p>ok</p>"})
    assert links.main(["x", str(tmp_path)]) == 0
    site(tmp_path, {"index.html": '<a href="gone/">x</a>'})
    assert links.main(["x", str(tmp_path)]) == 1
    assert "error:" in capsys.readouterr().out


# --- the build files ----------------------------------------------------------------------------------------------

CONFIG = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")


def nav_files() -> list[str]:
    return re.findall(r":\s+([\w./-]+\.md)\s*$", CONFIG, flags=re.MULTILINE)


def test_the_build_is_strict_and_uses_the_docs_folder():
    assert re.search(r"(?m)^strict: true$", CONFIG)
    assert re.search(r"(?m)^docs_dir: docs$", CONFIG)


def test_every_page_in_the_nav_exists_or_is_generated():
    generated = {"release-notes.md"}
    for name in nav_files():
        assert name in generated or (DOCS / name).exists(), name


def test_every_page_in_docs_is_in_the_nav_apart_from_the_adr_template():
    in_nav = set(nav_files())
    on_disk = {p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md")} - {"adr/template.md"}
    assert on_disk <= in_nav, sorted(on_disk - in_nav)
    assert "adr/template.md" not in in_nav


def test_the_standard_pages_of_this_phase_are_present():
    assert {"index.md", "security.md", "known-limitations.md", "release-notes.md"} <= set(nav_files())


def test_no_page_claims_production_readiness_and_the_home_page_says_it_is_not():
    for page in DOCS.rglob("*.md"):
        assert not re.search(r"production[- ]ready", page.read_text(encoding="utf-8"), re.I), page.name
    assert '"production": false' in (DOCS / "index.md").read_text(encoding="utf-8")
    assert '"production": false' in (DOCS / "security.md").read_text(encoding="utf-8")


def test_the_site_description_does_not_claim_production_either():
    assert not re.search(r"production[- ]ready", CONFIG, re.I)
    assert "not production" in CONFIG


def test_mkdocs_is_pinned_in_its_own_group_so_the_runtime_lock_does_not_change():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["dependency-groups"]["docs"] == ["mkdocs==1.6.1"]
    assert "mkdocs" not in (ROOT / "requirements.lock.txt").read_text(encoding="utf-8")


def test_the_built_site_is_not_committed():
    assert re.search(r"(?m)^site/$", (ROOT / ".gitignore").read_text(encoding="utf-8"))


# --- the workflow -------------------------------------------------------------------------------------------------

WORKFLOW = (ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")


def test_only_the_deploy_job_can_write_to_pages_and_never_for_a_pull_request():
    head, _, rest = WORKFLOW.partition("\njobs:\n")
    assert "pages: write" not in head and "id-token" not in head
    build, _, deploy = rest.partition("\n  deploy:\n")
    assert "pages: write" not in build and "id-token" not in build
    assert "pages: write" in deploy and "id-token: write" in deploy
    assert "github.event_name != 'pull_request'" in deploy
    assert "github.ref == 'refs/heads/main'" in deploy
    assert "environment:" in deploy and "github-pages" in deploy


def test_the_build_job_builds_strictly_and_checks_the_links_before_uploading():
    jobs = WORKFLOW.partition("\njobs:\n")[2]
    steps = ("mkdocs build --strict", "check-site-links.py", "upload-pages-artifact@")
    positions = [jobs.index(text) for text in steps]
    assert positions == sorted(positions)
