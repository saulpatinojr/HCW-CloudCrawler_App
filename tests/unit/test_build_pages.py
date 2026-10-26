"""scripts/build-pages.py and the guide pages in docs/ (ticket #11).

The script is the GitHub Pages builder merged in pull request 49; these tests cover the guide pages added to it: every
page in docs/ must have a menu entry, the whole site must build with every internal link and fragment resolving, and
no page may claim the appliance is ready for production (`/api/health` reports `production: false`). They need
markdown-it-py, which is installed with the default packages (a dependency of rich) and with the docs group."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("markdown_it")

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


def _load():
    spec = importlib.util.spec_from_file_location("build_pages", ROOT / "scripts" / "build-pages.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bp = _load()
GUIDE_PAGES = sorted(p for p in DOCS.glob("*.md"))


def test_every_guide_page_in_docs_has_a_menu_entry():
    assert bp.unlisted_doc_pages(ROOT) == []


def test_every_listed_guide_page_exists():
    for stem, _, _ in bp.DOC_PAGES:
        assert (DOCS / f"{stem}.md").exists(), stem


PROCEDURE_PAGES = (
    "quick-start",
    "installation",
    "configuration",
    "deployment",
    "operations",
    "testing",
    "troubleshooting",
)


@pytest.mark.parametrize("stem", PROCEDURE_PAGES)
def test_a_procedure_page_says_what_you_should_see_and_shows_commands(stem):
    text = (DOCS / f"{stem}.md").read_text(encoding="utf-8")
    assert "You should see" in text
    assert "```" in text, "a procedure page shows the commands to paste"


def test_an_unlisted_page_is_reported(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "quick-start.md").write_text("# a\n", encoding="utf-8")
    (tmp_path / "docs" / "secret-notes.md").write_text("# b\n", encoding="utf-8")
    assert bp.unlisted_doc_pages(tmp_path) == ["secret-notes.md"]


def test_a_listed_page_that_does_not_exist_yet_is_left_out_of_the_site(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "quick-start.md").write_text("# a\n", encoding="utf-8")
    assert [p.source for p in bp.doc_pages(tmp_path)] == ["docs/quick-start.md"]


def test_the_menu_lists_each_existing_guide_page_once_and_no_site_path_collides():
    outs = [out for _, out, _ in bp.DOC_PAGES]
    assert len(outs) == len(set(outs))
    site_outs = [p.out for p in bp.pages(ROOT)]
    assert len(site_outs) == len(set(site_outs)), "two sources would write the same file"
    targets = {n.target for n in bp.NAVIGATION}
    for page in bp.doc_pages(ROOT):
        assert page.out in targets


def test_the_whole_site_builds_and_every_internal_link_and_fragment_resolves(tmp_path):
    problems = bp.build(ROOT, tmp_path, "") + bp.check_site(tmp_path)
    assert problems == []
    for page in bp.doc_pages(ROOT):
        assert (tmp_path / page.out).exists(), page.out


def test_every_built_page_carries_the_not_production_notice(tmp_path):
    bp.build(ROOT, tmp_path, "")
    for file in tmp_path.rglob("*.html"):
        assert "Not production" in file.read_text(encoding="utf-8"), file.name


def test_the_checker_reports_a_broken_link_and_a_broken_fragment(tmp_path):
    head = '<title>t</title><meta name="viewport" content="width=device-width">'
    (tmp_path / "index.html").write_text(
        f'<html><head>{head}</head><body><a href="gone.html">a</a><a href="other.html#nope">b</a></body></html>',
        encoding="utf-8",
    )
    (tmp_path / "other.html").write_text(f'<html><head>{head}</head><body id="top"></body></html>', encoding="utf-8")
    found = bp.check_site(tmp_path)
    assert any("gone.html" in p for p in found) and any("#nope" in p for p in found)


@pytest.mark.parametrize("page", GUIDE_PAGES, ids=lambda p: p.name)
def test_a_guide_page_uses_plain_markdown_and_makes_no_production_claim(page):
    text = page.read_text(encoding="utf-8")
    assert not re.search(r"(?m)^!!! ", text), "MkDocs admonitions are not rendered by this builder; use a blockquote"
    assert not re.search(r"production[- ]ready", text, re.I)
    assert not re.search(r"(?i)\bis (?:fully )?ready for production\b", text)


def test_the_overview_pages_say_the_appliance_is_not_production():
    for name in ("product-overview.md", "known-limitations.md", "security.md"):
        assert '"production": false' in (DOCS / name).read_text(encoding="utf-8"), name
