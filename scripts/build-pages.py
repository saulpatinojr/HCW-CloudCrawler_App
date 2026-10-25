"""Build the GitHub Pages site from the repository's own Markdown, then check every link in what was built.

Why this exists: the site must say only what the repository already says, so it is rendered from the files the
repository keeps anyway (README, VALIDATION, CHANGELOG, CONTRIBUTING, the security policy and the ADRs) and nothing
is written twice. There is no second copy of the text to drift out of date.

What it does:

* renders each source page with markdown-it-py (CommonMark plus tables and strikethrough; raw HTML in the sources is
  escaped, never passed through) into one self-contained HTML file with a small inline style sheet, no script and no
  external request;
* gives every heading the id GitHub gives it, so a link such as `#signing-in-with-microsoft-entra` works on the site
  and on GitHub alike;
* rewrites relative links: to another site page it becomes a relative link to that page, to any other file in the
  repository it becomes a link to that file on GitHub (a source link that points at nothing stops the build);
* checks the built site: every internal link and every `#fragment` must resolve, every page must have a title and a
  viewport tag (the phone-sized screen), and no link may use plain http.

Run it from the repository root: `uv sync --locked --only-group docs`, then
`uv run --locked --only-group docs python scripts/build-pages.py`. It writes `_site/` and exits 1 on any problem.
"""

from __future__ import annotations

import argparse
import html
import os
import posixpath
import re
import shutil
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.token import Token

REPO = "saulpatinojr/HCW-CloudCrawler_App"
REPO_URL = f"https://github.com/{REPO}"
SITE_NAME = "HCW Cloud Crawler"
ROOT = Path(__file__).resolve().parent.parent

NOTICE = (
    "Not production. This is the upstream reference implementation of Cloud Crawler: the running appliance reports "
    "<code>production: false</code> on <code>/api/health</code>, and the Status section of the home page lists what "
    "exists and what does not yet."
)


@dataclass(frozen=True)
class Page:
    source: str  # path in the repository, with forward slashes
    out: str  # path in the site, with forward slashes
    label: str  # the page's name in the navigation and in <title> when the source has no heading


@dataclass(frozen=True)
class NavLink:
    label: str
    target: str  # a site path, optionally with #fragment


def adr_pages(root: Path) -> list[Page]:
    records = sorted((root / "docs" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md"))
    return [Page(f"docs/adr/{p.name}", f"architecture/{p.stem}.html", p.stem) for p in records]


def pages(root: Path) -> list[Page]:
    return [
        Page("README.md", "index.html", "Home"),
        Page("docs/adr/README.md", "architecture/index.html", "Architecture decisions"),
        *adr_pages(root),
        Page("VALIDATION.md", "validation.html", "Validation record and known limitations"),
        Page("CHANGELOG.md", "release-notes.html", "Release notes"),
        Page("CONTRIBUTING.md", "contributing.html", "Contributing"),
        Page(".github/SECURITY.md", "security.html", "Security policy"),
    ]


# Sections of the README that answer the usual documentation questions. Each target is checked at build time, so a
# renamed heading breaks the build instead of leaving a dead menu entry.
NAVIGATION = [
    NavLink("Home", "index.html"),
    NavLink("What it does", "index.html#what-it-does"),
    NavLink("Status", "index.html#status"),
    NavLink("Getting started", "index.html#getting-started"),
    NavLink("Microsoft Entra sign-in", "index.html#signing-in-with-microsoft-entra"),
    NavLink("Releasing the engine", "index.html#releasing-the-engine"),
    NavLink("Branch and tag protection", "index.html#branch-and-tag-protection"),
    NavLink("Architecture decisions", "architecture/index.html"),
    NavLink("Validation and known limitations", "validation.html"),
    NavLink("Release notes", "release-notes.html"),
    NavLink("Contributing", "contributing.html"),
    NavLink("Security policy", "security.html"),
]

STYLE = """
:root{color-scheme:light dark;--bg:#fff;--fg:#1b1f24;--muted:#57606a;--line:#d0d7de;--accent:#0b57d0;--code:#f3f4f6;
--warn-bg:#fff4ce;--warn-fg:#4d3b00}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#9da7b3;--line:#30363d;--accent:#79b8ff;
--code:#161b22;--warn-bg:#3b2f00;--warn-fg:#ffe9a8}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent)}
.notice{background:var(--warn-bg);color:var(--warn-fg);padding:.6rem 1rem;font-size:.95rem}
.layout{display:flex;flex-wrap:wrap;gap:0 2rem;max-width:72rem;margin:0 auto;padding:0 1rem}
nav{flex:1 1 15rem;padding:1rem 0}
nav .site{font-weight:700;display:block;margin-bottom:.5rem;color:var(--fg);text-decoration:none}
nav ul{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:.25rem .9rem}
main{flex:3 1 28rem;min-width:0;padding:1rem 0 3rem}
@media (min-width:60rem){nav{position:sticky;top:0;align-self:flex-start;max-height:100vh;overflow-y:auto}
nav ul{display:block}nav li{margin:.2rem 0}}
h1,h2,h3,h4{line-height:1.25;overflow-wrap:anywhere}
h2{border-bottom:1px solid var(--line);padding-bottom:.3rem;margin-top:2rem}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.9em;background:var(--code);
border-radius:4px}
code{padding:.1em .3em;overflow-wrap:anywhere}
pre{padding:.8rem 1rem;overflow-x:auto}pre code{padding:0;background:none;overflow-wrap:normal}
.table-wrap{overflow-x:auto;margin:1rem 0}
table{border-collapse:collapse;min-width:100%}th,td{border:1px solid var(--line);padding:.4rem .6rem;text-align:left;
vertical-align:top}
blockquote{margin:1rem 0;padding:0 1rem;border-left:4px solid var(--line);color:var(--muted)}
img{max-width:100%;height:auto}
footer{border-top:1px solid var(--line);padding:1rem 0 2rem;color:var(--muted);font-size:.9rem}
"""


def github_slug(text: str, seen: dict[str, int]) -> str:
    """The id GitHub gives a heading: lower case, punctuation dropped, spaces to hyphens, -N for repeats."""
    base = re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")
    count = seen.get(base, 0)
    seen[base] = count + 1
    return base if count == 0 else f"{base}-{count}"


def inline_text(token: Token) -> str:
    return "".join(c.content for c in (token.children or []) if c.type in {"text", "code_inline"})


def make_markdown() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])

    def table_open(self: object, tokens: list[Token], idx: int, options: object, env: object) -> str:
        return '<div class="table-wrap"><table>\n'

    def table_close(self: object, tokens: list[Token], idx: int, options: object, env: object) -> str:
        return "</table></div>\n"

    md.add_render_rule("table_open", table_open)
    md.add_render_rule("table_close", table_close)
    return md


def repo_link(root: Path, repo_path: str) -> str:
    kind = "tree" if (root / repo_path).is_dir() else "blob"
    return f"{REPO_URL}/{kind}/main/{repo_path}"


def rewrite_href(root: Path, page: Page, href: str, by_source: dict[str, Page], errors: list[str]) -> str:
    if href.startswith("#") or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href):
        return href  # a fragment on the same page, or an absolute URL: untouched
    path, _, fragment = href.partition("#")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(page.source), path))
    suffix = f"#{fragment}" if fragment else ""
    if resolved in by_source:
        target = by_source[resolved].out
        return posixpath.relpath(target, posixpath.dirname(page.out) or ".") + suffix
    if resolved.startswith("..") or not (root / resolved).exists():
        errors.append(f"{page.source}: the link '{href}' points at nothing in the repository")
        return href
    return repo_link(root, resolved) + suffix


def render_page(
    root: Path, page: Page, by_source: dict[str, Page], md: MarkdownIt, errors: list[str]
) -> tuple[str, str]:
    """(title, body HTML) for one source page."""
    tokens = md.parse((root / page.source).read_text(encoding="utf-8"))
    seen: dict[str, int] = {}
    title = page.label
    first_heading = True
    for idx, token in enumerate(tokens):
        if token.type == "heading_open":
            text = inline_text(tokens[idx + 1])
            token.attrSet("id", github_slug(text, seen))
            if first_heading and token.tag == "h1":
                title = text
            first_heading = False
        for child in token.children or []:
            if child.type == "link_open":
                child.attrSet("href", rewrite_href(root, page, str(child.attrGet("href") or ""), by_source, errors))
    return title, md.renderer.render(tokens, md.options, {})


def site_href(here: str, target: str) -> str:
    path, _, fragment = target.partition("#")
    return posixpath.relpath(path, here) + (f"#{fragment}" if fragment else "")


def render_nav(page: Page) -> str:
    here = posixpath.dirname(page.out) or "."
    items = "\n".join(
        f'<li><a href="{html.escape(site_href(here, n.target))}">{html.escape(n.label)}</a></li>' for n in NAVIGATION
    )
    home = posixpath.relpath("index.html", here)
    return f'<nav aria-label="Site"><a class="site" href="{home}">{SITE_NAME}</a><ul>\n{items}\n</ul></nav>'


def render_document(page: Page, title: str, body: str, commit: str) -> str:
    built = f"Built from commit {html.escape(commit[:12])}. " if commit else ""
    source = f"{REPO_URL}/blob/main/{page.source}"
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)} | {SITE_NAME}</title>\n"
        f"<style>{STYLE}</style>\n</head>\n<body>\n"
        f'<div class="notice" role="note">{NOTICE}</div>\n'
        f'<div class="layout">\n{render_nav(page)}\n<main>\n{body}\n'
        f'<footer>{built}This page is rendered from <a href="{source}">{html.escape(page.source)}</a> in '
        f'<a href="{REPO_URL}">{REPO}</a>; the repository is the source of truth.</footer>\n'
        "</main>\n</div>\n</body>\n</html>\n"
    )


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.has_title = False
        self.has_viewport = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k: v or "" for k, v in attrs}
        if "id" in values:
            self.ids.add(values["id"])
        if tag in {"a", "link"} and "href" in values:
            self.links.append(values["href"])
        if tag in {"img", "script", "iframe"} and "src" in values:
            self.links.append(values["src"])
        if tag == "title":
            self.has_title = True
        if tag == "meta" and values.get("name") == "viewport":
            self.has_viewport = True


def check_site(out: Path) -> list[str]:
    """Every problem found in the built site (an empty list means it passed)."""
    parsed: dict[str, LinkCollector] = {}
    for file in sorted(out.rglob("*.html")):
        collector = LinkCollector()
        collector.feed(file.read_text(encoding="utf-8"))
        parsed[file.relative_to(out).as_posix()] = collector
    problems: list[str] = []
    for name, found in parsed.items():
        if not found.has_title:
            problems.append(f"{name}: no <title>")
        if not found.has_viewport:
            problems.append(f"{name}: no viewport meta tag (the page would not fit a phone)")
        for href in found.links:
            if href.startswith("http://"):
                problems.append(f"{name}: plain http link {href}")
                continue
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href):
                continue  # https and mailto: not fetched here
            path, _, fragment = href.partition("#")
            target = name if not path else posixpath.normpath(posixpath.join(posixpath.dirname(name), path))
            if target not in parsed:
                problems.append(f"{name}: broken link {href} (no page {target})")
            elif fragment and fragment not in parsed[target].ids:
                problems.append(f"{name}: broken link {href} (no #{fragment} on {target})")
    return problems


def build(root: Path, out: Path, commit: str) -> list[str]:
    site = pages(root)
    by_source = {p.source: p for p in site}
    md = make_markdown()
    errors: list[str] = []
    for page in site:
        title, body = render_page(root, page, by_source, md, errors)
        target = out / page.out
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_document(page, title, body, commit), encoding="utf-8", newline="\n")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("--out", default="_site", help="output directory (default: _site)")
    parser.add_argument("--commit", default=os.environ.get("GITHUB_SHA", ""), help="commit shown in the footer")
    args = parser.parse_args()
    out = (ROOT / args.out).resolve()
    if out == ROOT or ROOT not in out.parents:
        print(f"error: --out must be a folder inside the repository, not {out}", file=sys.stderr)
        return 1
    if out.exists():
        shutil.rmtree(out)
    problems = build(ROOT, out, args.commit)
    problems += check_site(out)
    if problems:
        print("\n".join(f"error: {p}" for p in problems), file=sys.stderr)
        return 1
    count = len(list(out.rglob("*.html")))
    print(f"built {count} pages in {out.relative_to(ROOT)}; every internal link and fragment resolves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
