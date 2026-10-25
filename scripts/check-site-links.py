"""Check the built documentation site: every link inside the site lands on a real page or heading.

Usage: python scripts/check-site-links.py [SITE_DIR]   (default: site)

It reads every .html file under SITE_DIR and fails (exit 1, one line per problem) when

* a relative link or image points at a file that is not in the site;
* a link with a #fragment points at a page that has no element with that id (or name);
* a page has no viewport meta tag (without it a phone shows the page zoomed out, not at its own width);
* a page, other than the theme's own 404 and search pages, is not reachable from the home page by following links.

The 404 page is not link-checked: it is served from any address, so the theme writes its links from the site's root
(for example /HCW-CloudCrawler_App/css/theme.css), which cannot be resolved against a folder of files.

Links to other sites (http, https, mailto) are listed as a count and are NOT fetched: this check runs offline, so a
broken outside link would not be found here. Standard library only, so it needs no install.
"""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urldefrag, urlparse

SKIP_SCHEMES = ("http", "https", "mailto", "tel", "javascript", "data")
THEME_PAGES = ("404.html", "search.html")


class PageReader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.viewport = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: (value or "") for name, value in attrs}
        for key in ("id", "name"):
            if values.get(key):
                self.ids.add(values[key])
        if tag == "meta" and values.get("name", "").lower() == "viewport":
            self.viewport = True
        if tag in ("a", "link") and values.get("href"):
            self.links.append(values["href"])
        elif tag in ("img", "script", "source") and values.get("src"):
            self.links.append(values["src"])


def read_page(path: Path) -> PageReader:
    reader = PageReader()
    reader.feed(path.read_text(encoding="utf-8"))
    return reader


def target_file(site: Path, page: Path, href: str) -> Path | None:
    """The file in the site a link from `page` points at, or None for a link to another site."""
    parsed = urlparse(href)
    if parsed.scheme in SKIP_SCHEMES or href.startswith("//"):
        return None
    path = unquote(parsed.path)
    if not path:
        return page
    base = site if path.startswith("/") else page.parent
    candidate = (base / path.lstrip("/")).resolve()
    if candidate.is_dir() or path.endswith("/"):
        candidate = candidate / "index.html"
    return candidate


def check(site: Path) -> tuple[list[str], int, int]:
    """(problems, number of pages, number of links to other sites)"""
    site = site.resolve()
    pages = sorted(page for page in site.rglob("*.html") if page.name != "404.html")
    if not pages:
        return [f"no .html files under {site}: build the site first"], 0, 0
    readers = {page: read_page(page) for page in pages}
    problems: list[str] = []
    outside = 0
    edges: dict[Path, set[Path]] = {page: set() for page in pages}
    for page, reader in readers.items():
        name = page.relative_to(site).as_posix()
        if not reader.viewport:
            problems.append(f"{name}: no viewport meta tag")
        for href in reader.links:
            parsed = urlparse(href)
            if parsed.scheme in SKIP_SCHEMES or href.startswith("//"):
                outside += 1
                continue
            file = target_file(site, page, href)
            if file is None:
                continue
            try:
                file.relative_to(site)
            except ValueError:
                problems.append(f"{name}: {href} leaves the site")
                continue
            if not file.exists():
                problems.append(f"{name}: {href} points at a file that is not in the site")
                continue
            edges[page].add(file)
            fragment = unquote(urldefrag(href)[1])
            if fragment and file.suffix == ".html":
                target = readers.get(file) or read_page(file)
                if fragment not in target.ids:
                    problems.append(f"{name}: {href} points at a heading that does not exist")
    home = site / "index.html"
    if home.exists():
        seen, queue = {home}, [home]
        while queue:
            for nxt in edges.get(queue.pop(), ()):
                if nxt not in seen and nxt in edges:
                    seen.add(nxt)
                    queue.append(nxt)
        for page in pages:
            if page not in seen and page.name not in THEME_PAGES:
                problems.append(f"{page.relative_to(site).as_posix()}: no link path from the home page reaches it")
    else:
        problems.append("there is no index.html at the root of the site")
    return problems, len(pages), outside


def main(argv: list[str]) -> int:
    site = Path(argv[1]) if len(argv) > 1 else Path("site")
    problems, pages, outside = check(site)
    for problem in problems:
        print(f"error: {problem}")
    print(f"{pages} pages checked; {outside} links to other sites were not fetched (offline check)")
    if problems:
        print(f"{len(problems)} problem(s)")
        return 1
    print("every link inside the site lands")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
