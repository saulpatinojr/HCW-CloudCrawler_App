"""scripts/check-release-version.py: the permanent guard that a release tag, every package version, the changelog and
the built files agree. A v* tag cannot be moved or deleted (ruleset "Protect release tags"), so these cases are the
only chance to catch a wrong one. No network; the git cases build a throwaway repository."""

from __future__ import annotations

import datetime
import importlib.util
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check-release-version.py"
ENGINE = "packages/cloud-crawler-core"


def _load():
    spec = importlib.util.spec_from_file_location("check_release_version", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load()

CHANGELOG = """# Changelog

## [Unreleased]

## [0.1.0] - 2026-10-25

### Added

- The first release.

## [0.0.9] - 2026-01-01

### Fixed

- Something older.
"""


def make_repo(root: Path, *, version: str = "0.1.0", changelog: str = CHANGELOG, **override: str) -> Path:
    """A minimal tree with the files the guard reads. `override` replaces one version by its label key."""
    versions = {
        "engine_toml": version,
        "app_toml": version,
        "engine_py": version,
        "app_py": version,
        "lock_engine": version,
        "lock_app": version,
    }
    versions.update(override)
    files = {
        f"{ENGINE}/pyproject.toml": f'[project]\nname = "cloud-crawler-core"\nversion = "{versions["engine_toml"]}"\n',
        "pyproject.toml": f'[project]\nname = "cloud-crawler-appliance"\nversion = "{versions["app_toml"]}"\n',
        f"{ENGINE}/src/cloud_crawler_core/__init__.py": f'"""x"""\n\n__version__ = "{versions["engine_py"]}"\n',
        "src/cloud_crawler_appliance/__init__.py": f'__version__ = "{versions["app_py"]}"\nADDON_ID = "x"\n',
        "uv.lock": (
            "version = 1\n\n"
            f'[[package]]\nname = "cloud-crawler-appliance"\nversion = "{versions["lock_app"]}"\n\n'
            f'[[package]]\nname = "cloud-crawler-core"\nversion = "{versions["lock_engine"]}"\n\n'
            '[[package]]\nname = "pydantic"\nversion = "9.9.9"\n'
        ),
        "CHANGELOG.md": changelog,
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    """The fixture changelog is dated 2026-10-25; the clock must not decide whether these tests pass."""
    monkeypatch.setattr(guard, "utc_today", lambda: datetime.date(2026, 10, 25))


def problems(root: Path, tag: str | None = None, dist: Path | None = None) -> list[str]:
    return guard.check(root, tag, dist)[0]


def test_this_repository_is_consistent():
    found, errors = guard.read_versions(ROOT)
    assert errors == []
    assert len(found) == 6 and len(set(found.values())) == 1
    assert problems(ROOT) == []


def test_script_runs_as_a_program_and_succeeds_here():
    result = subprocess.run([sys.executable, "-I", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("release version consistent: ")


def test_consistent_tree_passes(tmp_path):
    root = make_repo(tmp_path)
    assert guard.check(root) == ([], "0.1.0")
    assert problems(root, "v0.1.0") == []
    assert problems(root, "refs/tags/v0.1.0") == []


@pytest.mark.parametrize("which", ["engine_toml", "app_toml", "engine_py", "app_py", "lock_engine", "lock_app"])
def test_any_single_disagreeing_file_fails(tmp_path, which):
    root = make_repo(tmp_path, **{which: "0.1.1"})
    found = problems(root)
    assert found and "differs between files (0.1.0, 0.1.1)" in found[0]
    assert guard.check(root)[1] is None


@pytest.mark.parametrize("version", ["0.1.0rc1", "0.1.0-rc.1", "1.0", "01.2.3", "v0.1.0"])
def test_only_plain_x_y_z_is_a_release_version(tmp_path, version):
    root = make_repo(tmp_path, version=version)
    assert any("is not a plain X.Y.Z" in p for p in problems(root))


def test_missing_and_unreadable_sources_are_reported_not_raised(tmp_path):
    root = make_repo(tmp_path)
    (root / "src/cloud_crawler_appliance/__init__.py").write_text("ADDON_ID = 'x'\n", encoding="utf-8")
    (root / "pyproject.toml").unlink()
    (root / "uv.lock").write_text("[[package]]\nname = 'pydantic'\nversion = '1'\n", encoding="utf-8")
    found = problems(root)
    assert any("no version found in src/cloud_crawler_appliance/__init__.py" in p for p in found)
    assert any("cannot read pyproject.toml" in p for p in found)
    assert any("uv.lock has no entry for cloud-crawler-core" in p for p in found)
    (root / "uv.lock").write_text("not [valid toml", encoding="utf-8")
    assert any("cannot read uv.lock" in p for p in problems(root))
    (root / "uv.lock").unlink()
    assert any("cannot read uv.lock" in p for p in problems(root))


@pytest.mark.parametrize("tag", ["v0.1.1", "0.1.0", "v0.1", "v0.1.0-rc.1", "release-1", "vtest", "v0.1.0 "])
def test_a_tag_that_is_not_v_plus_the_version_fails(tmp_path, tag):
    found = problems(make_repo(tmp_path), tag)
    assert any(f"tag {tag!r} is not v followed by X.Y.Z" in p or f"tag {tag} does not match" in p for p in found)


def test_changelog_must_have_a_dated_non_empty_section_for_a_tag(tmp_path):
    assert any(
        "no '## [0.1.0] - YYYY-MM-DD' section" in p
        for p in problems(make_repo(tmp_path, changelog="# Changelog\n"), "v0.1.0")
    )
    undated = CHANGELOG.replace("## [0.1.0] - 2026-10-25", "## [0.1.0]")
    assert any("has no release date" in p for p in problems(make_repo(tmp_path, changelog=undated), "v0.1.0"))
    baddate = CHANGELOG.replace("2026-10-25", "yesterday")
    assert any("has no release date" in p for p in problems(make_repo(tmp_path, changelog=baddate), "v0.1.0"))
    empty = CHANGELOG.replace("### Added\n\n- The first release.\n", "### Added\n")
    assert any("section for 0.1.0 is empty" in p for p in problems(make_repo(tmp_path, changelog=empty), "v0.1.0"))
    assert problems(make_repo(tmp_path, changelog=empty)) == []  # not a tag: the changelog is not required


def test_unreleased_entries_block_a_tag_but_not_ordinary_work(tmp_path):
    unreleased = CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Fixed\n\n- A late fix.\n")
    root = make_repo(tmp_path, changelog=unreleased)
    assert problems(root) == []
    assert any("still has entries under [Unreleased]" in p for p in problems(root, "v0.1.0"))
    only_headings = CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Fixed\n\n### Added\n")
    assert problems(make_repo(tmp_path, changelog=only_headings), "v0.1.0") == []


def test_changelog_sections_ignore_headings_inside_code_fences():
    text = (
        "## [1.0.0] - 2026-01-01\n\nText\n\n```markdown\n## [9.9.9] - 2030-01-01\n```\n\n## Other heading\n\nhidden\n"
    )
    sections = guard.changelog_sections(text)
    assert list(sections) == ["1.0.0"]
    assert "9.9.9" in sections["1.0.0"][1] and "hidden" not in sections["1.0.0"][1]


def test_a_version_prefix_does_not_pick_the_wrong_section():
    text = "## [10.1.0] - 2026-01-01\n\n- ten\n\n## [0.1.0] - 2025-01-01\n\n- zero\n"
    assert guard.changelog_sections(text)["0.1.0"] == ("2025-01-01", "- zero")


def build_dist(directory: Path, version: str = "0.1.0", inner: str | None = None, extra: tuple[str, ...] = ()) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(directory / f"cloud_crawler_core-{version}-py3-none-any.whl", "w") as archive:
        archive.writestr("cloud_crawler_core/__init__.py", f'__version__ = "{inner or version}"\n')
    (directory / f"cloud_crawler_core-{version}.tar.gz").write_bytes(b"sdist")
    for name in extra:
        (directory / name).write_text("x", encoding="utf-8")
    return directory


def test_dist_must_hold_exactly_the_wheel_and_sdist_for_the_version(tmp_path):
    root = make_repo(tmp_path / "repo")
    assert problems(root, dist=build_dist(tmp_path / "ok")) == []
    stray = build_dist(tmp_path / "stray", extra=(".gitignore", "notes.txt"))
    found = problems(root, dist=stray)
    assert any(".gitignore is not expected" in p for p in found) and any(
        "notes.txt is not expected" in p for p in found
    )
    older = build_dist(tmp_path / "older", version="0.0.9")
    found = problems(root, dist=older)
    assert any("cloud_crawler_core-0.1.0-py3-none-any.whl is missing" in p for p in found)
    assert any("cloud_crawler_core-0.0.9.tar.gz is not expected" in p for p in found)
    assert any("is missing" in p for p in problems(root, dist=tmp_path / "nowhere"))


def test_the_wheels_own_version_must_match_its_file_name(tmp_path):
    root = make_repo(tmp_path / "repo")
    found = problems(root, dist=build_dist(tmp_path / "lie", inner="0.0.9"))
    assert found == ["the wheel's own __version__ is 0.0.9, the file name says 0.1.0"]
    with zipfile.ZipFile(build_dist(tmp_path / "bare") / "cloud_crawler_core-0.1.0-py3-none-any.whl", "w") as archive:
        archive.writestr("cloud_crawler_core/other.py", "")
    assert any("own __version__ is none" in p for p in problems(root, dist=tmp_path / "bare"))


def test_notes_are_the_changelog_section(tmp_path, capsys):
    root = make_repo(tmp_path / "repo")
    notes = tmp_path / "notes.md"
    assert guard.main(["--root", str(root), "--tag", "v0.1.0", "--notes-out", str(notes)]) == 0
    assert notes.read_text(encoding="utf-8") == "### Added\n\n- The first release.\n"
    assert "tag v0.1.0" in capsys.readouterr().out


def test_notes_with_no_section_fail_and_write_nothing(tmp_path, capsys):
    root = make_repo(tmp_path / "repo", changelog="# Changelog\n")
    notes = tmp_path / "notes.md"
    assert guard.main(["--root", str(root), "--notes-out", str(notes)]) == 1
    assert not notes.exists()
    assert "missing or empty: there are no release notes" in capsys.readouterr().out


def test_a_dry_run_warns_about_unreleased_entries_but_still_writes_notes(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    unreleased = CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n- A late fix.\n")
    root = make_repo(tmp_path / "repo", changelog=unreleased)
    notes = tmp_path / "notes.md"
    assert guard.main(["--root", str(root), "--notes-out", str(notes)]) == 0
    assert notes.exists()
    assert "::warning::CHANGELOG.md still has entries under [Unreleased]" in capsys.readouterr().out


def test_failures_are_github_annotations_under_actions_and_plain_lines_otherwise(tmp_path, capsys, monkeypatch):
    root = make_repo(tmp_path, app_py="0.2.0")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert guard.main(["--root", str(root)]) == 1
    assert capsys.readouterr().out.startswith("::error::the version differs between files")
    monkeypatch.delenv("GITHUB_ACTIONS")
    assert guard.main(["--root", str(root)]) == 1
    assert capsys.readouterr().out.startswith("error: the version differs between files")


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def git(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *args],
        cwd=directory,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@needs_git
def test_only_a_commit_on_the_protected_branch_may_be_released(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "main commit")
    on_main = git(root, "rev-parse", "HEAD")
    git(root, "switch", "-q", "-c", "feature")
    (root / "extra.txt").write_text("unreviewed", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "feature commit")
    on_feature = git(root, "rev-parse", "HEAD")
    assert guard.on_branch(on_main, "main", root) is None
    assert "is not on main" in guard.on_branch(on_feature, "main", root)
    assert "could not compare" in guard.on_branch(on_main, "no-such-branch", root)

    monkeypatch.setenv("GITHUB_SHA", on_feature)
    assert guard.main(["--root", str(root), "--tag", "v0.1.0", "--ancestor-of", "main"]) == 1
    monkeypatch.setenv("GITHUB_SHA", on_main)
    assert guard.main(["--root", str(root), "--tag", "v0.1.0", "--ancestor-of", "main"]) == 0
    monkeypatch.delenv("GITHUB_SHA")
    git(root, "switch", "-q", "main")
    assert guard.main(["--root", str(root), "--tag", "v0.1.0", "--ancestor-of", "main"]) == 0


# --- the changelog parser: every way a wrong changelog used to look right ---------------------------------------------


def with_changelog(tmp_path: Path, text: str) -> Path:
    return make_repo(tmp_path, changelog=text)


@pytest.mark.parametrize(
    "heading",
    ["## [Unreleased]", "## [unreleased]", "## [UNRELEASED]", "## Unreleased", "## unreleased", "##  [Unreleased]"],
)
def test_unreleased_is_found_in_any_letter_case_with_or_without_brackets(tmp_path, heading):
    text = CHANGELOG.replace("## [Unreleased]", f"{heading}\n\n- A late fix.")
    found = problems(with_changelog(tmp_path, text), "v0.1.0")
    assert any("still has entries under [Unreleased]" in p for p in found), heading
    empty = CHANGELOG.replace("## [Unreleased]", heading)
    assert problems(with_changelog(tmp_path / "empty", empty), "v0.1.0") == []


def test_two_unreleased_headings_in_different_spellings_are_a_duplicate(tmp_path):
    text = CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n## unreleased\n\n- hidden\n")
    assert any("more than once" in p for p in problems(with_changelog(tmp_path, text), "v0.1.0"))


def test_a_duplicate_version_heading_is_refused_not_resolved_by_taking_the_last(tmp_path):
    text = CHANGELOG + "\n## [0.1.0] - 2026-10-25\n\n- A second, different section.\n"
    sections, duplicates = guard.parse_changelog(text)
    assert duplicates == ["0.1.0"] and sections["0.1.0"][1] == "### Added\n\n- The first release."
    found = problems(with_changelog(tmp_path, text), "v0.1.0")
    assert any("the heading '## [0.1.0]' more than once" in p for p in found)
    assert problems(with_changelog(tmp_path / "plain", text)) == [], "ordinary work is not held up by it"


@pytest.mark.parametrize("date", ["2026-13-45", "2026-02-30", "2026-00-10", "2027-02-29", "0000-01-01"])
def test_a_date_that_does_not_exist_is_refused(tmp_path, date):
    text = CHANGELOG.replace("2026-10-25", date)
    assert any("date that does not exist" in p for p in problems(with_changelog(tmp_path, text), "v0.1.0")), date


@pytest.mark.parametrize("date", ["20261025", "2026-1-5", "2026-W43-7", "２０２６-10-25", "2026-10-25T10:00"])
def test_only_the_plain_iso_date_shape_is_a_date(tmp_path, date):
    text = CHANGELOG.replace("2026-10-25", date)
    assert any("has no release date" in p for p in problems(with_changelog(tmp_path, text), "v0.1.0")), date


def test_a_date_in_the_future_is_refused_with_one_day_of_time_zone_slack(tmp_path):
    root = with_changelog(tmp_path / "a", CHANGELOG.replace("2026-10-25", "2026-10-26"))
    assert problems(root, "v0.1.0") == [], "tomorrow, because a release may be dated in a time zone ahead of UTC"
    root = with_changelog(tmp_path / "b", CHANGELOG.replace("2026-10-25", "2026-10-27"))
    found = problems(root, "v0.1.0")
    assert any("dated 2026-10-27, which is in the future (today is 2026-10-25)" in p for p in found)
    root = with_changelog(tmp_path / "c", CHANGELOG.replace("2026-10-25", "2999-01-01"))
    assert any("in the future" in p for p in problems(root, "v0.1.0"))


def test_the_real_clock_is_used_when_no_date_is_given(monkeypatch):
    monkeypatch.undo()
    assert guard.utc_today() == datetime.datetime.now(datetime.UTC).date()


def test_headings_inside_tilde_fences_are_ignored_and_a_fence_closes_like_commonmark():
    text = "## [1.0.0] - 2026-01-01\n\nText\n\n~~~markdown\n## [9.9.9] - 2030-01-01\n~~~\n\nAfter\n"
    sections = guard.changelog_sections(text)
    assert list(sections) == ["1.0.0"] and "After" in sections["1.0.0"][1]
    # a backtick fence is not closed by tildes, nor by a shorter fence, nor by a line with text after it
    text = "## [1.0.0] - 2026-01-01\n\n```\n~~~\n## [9.9.9] - 2030-01-01\n``\n```` x\n```\n\n## [0.9.0] - 2025-01-01\n"
    assert list(guard.changelog_sections(text)) == ["1.0.0", "0.9.0"]
    text = "## [1.0.0] - 2026-01-01\n\n````\n```\n## [9.9.9] - 2030-01-01\n````\n\n## [0.9.0] - 2025-01-01\n\nOld\n"
    assert list(guard.changelog_sections(text)) == ["1.0.0", "0.9.0"]
    # an unclosed fence hides the rest of the file: nothing after it can become a heading
    assert list(guard.changelog_sections("## [1.0.0] - 2026-01-01\n\n~~~\n## [0.9.0] - 2025-01-01\n")) == ["1.0.0"]
    # an inline run of backticks is not a fence
    inline = "## [1.0.0] - 2026-01-01\n\n``` not a fence ```\n## [0.9.0] - 2025-01-01\n"
    assert list(guard.changelog_sections(inline)) == ["1.0.0", "0.9.0"]


def test_a_heading_inside_an_html_comment_is_not_a_heading():
    text = "## [1.0.0] - 2026-01-01\n\n<!--\n## [9.9.9] - 2030-01-01\n-->\n\nText\n\n## [0.9.0] - 2025-01-01\n\nOld\n"
    assert list(guard.changelog_sections(text)) == ["1.0.0", "0.9.0"]
    one_line = "## [1.0.0] - 2026-01-01\n\n<!-- a note -->\n## [0.9.0] - 2025-01-01\n\nOld\n"
    assert list(guard.changelog_sections(one_line)) == ["1.0.0", "0.9.0"]


def test_link_reference_definitions_at_the_end_are_not_release_notes(tmp_path):
    definitions = "\n[Unreleased]: https://example.invalid/compare\n[0.1.0]: https://example.invalid/tag\n"
    root = make_repo(tmp_path / "repo", changelog=CHANGELOG + definitions)
    assert guard.changelog_sections(CHANGELOG + definitions)["0.0.9"][1] == "### Fixed\n\n- Something older."
    notes = tmp_path / "notes.md"
    assert guard.main(["--root", str(root), "--tag", "v0.1.0", "--notes-out", str(notes)]) == 0
    assert notes.read_text(encoding="utf-8") == "### Added\n\n- The first release.\n"
    # definitions that are the only thing under the 0.1.0 heading are not content
    only_definitions = CHANGELOG.replace("- The first release.\n", "[x]: https://example.invalid/x\n")
    root = make_repo(tmp_path / "d", changelog=only_definitions)
    assert any("section for 0.1.0 is empty" in p for p in problems(root, "v0.1.0"))
    # a definition in the middle of the notes stays, because the text above it may use it
    middle = CHANGELOG.replace("- The first release.\n", "- See [x].\n\n[x]: https://example.invalid/x\n\n- More.\n")
    assert "[x]: https://example.invalid/x" in guard.changelog_sections(middle)["0.1.0"][1]


@pytest.mark.parametrize(
    "comment",
    ["<!-- nothing yet -->", "<!--\nTODO: write the notes\n-->", "<!-- a --><!-- b -->"],
)
def test_an_html_comment_is_not_content(tmp_path, comment):
    release = CHANGELOG.replace("- The first release.\n", f"{comment}\n")
    found = problems(with_changelog(tmp_path / "r", release), "v0.1.0")
    assert any("section for 0.1.0 is empty" in p for p in found), comment
    unreleased = CHANGELOG.replace("## [Unreleased]\n", f"## [Unreleased]\n\n{comment}\n")
    assert problems(with_changelog(tmp_path / "u", unreleased), "v0.1.0") == [], comment


def test_an_unterminated_html_comment_hides_the_rest_so_the_check_fails_loudly(tmp_path):
    text = CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n<!-- unterminated\n")
    found = problems(with_changelog(tmp_path, text), "v0.1.0")
    assert found == ["CHANGELOG.md has no '## [0.1.0] - YYYY-MM-DD' section"]


def test_text_next_to_an_html_comment_is_still_content():
    assert guard.has_content("<!-- c --> real words")
    assert guard.has_content("<!-- c -->\n- an entry\n<!-- d -->")
    assert not guard.has_content("### Added\n\n<!-- c -->\n\n### Fixed\n")
    assert not guard.has_content("[x]: https://example.invalid/x\n\n### Fixed\n"), "a definition renders as nothing"


# --- the dry run (--rehearse) is the tag run without the tag ------------------------------------------------------


def git_repo(root: Path) -> Path:
    """`root` as a git repository with one commit on main, so that the rehearsal's tag and ancestry lookups work."""
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "main commit")
    return root


def errors(capsys) -> list[str]:
    """The problem lines printed so far, whether they are GitHub annotations (under Actions) or plain lines."""
    lines = capsys.readouterr().out.splitlines()
    return [line.removeprefix("::error::").removeprefix("error: ") for line in lines if "error" in line.split(" ")[0]]


@needs_git
def test_rehearse_derives_the_tag_and_runs_every_tag_check(tmp_path, capsys):
    root = git_repo(make_repo(tmp_path / "ok"))
    assert guard.main(["--root", str(root), "--rehearse"]) == 0
    assert "release version consistent: 0.1.0, tag v0.1.0" in capsys.readouterr().out
    bad = {
        "missing section": "# Changelog\n",
        "undated": CHANGELOG.replace(" - 2026-10-25", ""),
        "empty section": CHANGELOG.replace("### Added\n\n- The first release.\n", ""),
        "impossible date": CHANGELOG.replace("2026-10-25", "2026-13-45"),
        "future date": CHANGELOG.replace("2026-10-25", "2999-01-01"),
        "unreleased entries": CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n- late\n"),
        "lowercase unreleased entries": CHANGELOG.replace("## [Unreleased]\n", "## unreleased\n\n- late\n"),
        "duplicate heading": CHANGELOG + "\n## [0.1.0] - 2026-10-25\n\n- again\n",
    }
    for label, text in bad.items():
        root = git_repo(make_repo(tmp_path / label.replace(" ", "-"), changelog=text))
        assert guard.main(["--root", str(root), "--rehearse"]) == 1, label
        rehearsal = errors(capsys)
        assert guard.main(["--root", str(root), "--tag", "v0.1.0"]) == 1, f"{label}: the tag run must refuse it too"
        assert rehearsal and rehearsal == errors(capsys), f"{label}: the dry run and the tag run must say the same"


def test_rehearse_is_red_for_a_disagreeing_version_and_is_never_a_second_way_to_pick_the_tag(tmp_path, capsys):
    root = make_repo(tmp_path / "repo", app_py="0.2.0")
    assert guard.main(["--root", str(root), "--rehearse"]) == 1
    assert "the version differs between files" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        guard.main(["--root", str(root), "--rehearse", "--tag", "v0.1.0"])


@needs_git
def test_rehearse_also_checks_the_built_files(tmp_path, capsys):
    root = git_repo(make_repo(tmp_path / "repo"))
    assert guard.main(["--root", str(root), "--rehearse", "--dist", str(build_dist(tmp_path / "ok"))]) == 0
    lie = build_dist(tmp_path / "lie", inner="0.0.9")
    assert guard.main(["--root", str(root), "--rehearse", "--dist", str(lie)]) == 1
    assert "the wheel's own __version__ is 0.0.9" in capsys.readouterr().out


@needs_git
def test_rehearse_checks_ancestry_and_that_the_tag_is_still_free(tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "main commit")
    on_main = git(root, "rev-parse", "HEAD")
    git(root, "switch", "-q", "-c", "feature")
    (root / "extra.txt").write_text("unreviewed", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "feature commit")
    on_feature = git(root, "rev-parse", "HEAD")
    monkeypatch.setenv("GITHUB_SHA", on_main)
    assert guard.main(["--root", str(root), "--rehearse", "--ancestor-of", "main"]) == 0
    monkeypatch.setenv("GITHUB_SHA", on_feature)
    assert guard.main(["--root", str(root), "--rehearse", "--ancestor-of", "main"]) == 1
    assert "is not on main" in capsys.readouterr().out
    monkeypatch.setenv("GITHUB_SHA", on_main)
    git(root, "tag", "-a", "v0.1.0", on_main, "-m", "already released")
    assert guard.main(["--root", str(root), "--rehearse", "--ancestor-of", "main"]) == 1
    assert "the tag v0.1.0 already exists" in capsys.readouterr().out
    # the real tag run is the one that creates the tag, so the existing tag is not an error there
    assert guard.main(["--root", str(root), "--tag", "v0.1.0", "--ancestor-of", "main"]) == 0


@needs_git
def test_rehearse_reports_a_tag_lookup_that_cannot_be_made(tmp_path, capsys):
    root = make_repo(tmp_path)  # a directory that is not a git repository
    assert guard.main(["--root", str(root), "--rehearse"]) == 1
    assert "could not look up the tag v0.1.0" in capsys.readouterr().out


# --- a stale date is advisory -------------------------------------------------------------------------------------


def test_a_stale_release_date_is_a_warning_not_a_refusal(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    week_old = make_repo(tmp_path / "a", changelog=CHANGELOG.replace("2026-10-25", "2026-10-18"))
    monkeypatch.setattr(guard, "utc_today", lambda: datetime.date(2026, 10, 25))
    assert guard.main(["--root", str(week_old), "--tag", "v0.1.0"]) == 0
    assert "warning" not in capsys.readouterr().out, "seven days old is still fresh"
    stale = make_repo(tmp_path / "b", changelog=CHANGELOG.replace("2026-10-25", "2026-10-17"))
    assert guard.main(["--root", str(stale), "--tag", "v0.1.0"]) == 0, "the guard refuses only future dates"
    out = capsys.readouterr().out
    assert "warning: the CHANGELOG.md section for 0.1.0 is dated 2026-10-17, 8 days ago" in out
    assert "release version consistent: 0.1.0, tag v0.1.0" in out
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert guard.main(["--root", str(stale), "--tag", "v0.1.0"]) == 0
    assert "::warning::the CHANGELOG.md section for 0.1.0 is dated 2026-10-17" in capsys.readouterr().out


def test_no_stale_warning_without_a_tag_or_when_the_date_is_refused_anyway(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    stale = make_repo(tmp_path / "a", changelog=CHANGELOG.replace("2026-10-25", "2020-01-01"))
    assert guard.main(["--root", str(stale)]) == 0
    assert "warning" not in capsys.readouterr().out
    assert guard.stale_date_warning(stale / "missing", "0.1.0", datetime.date(2026, 10, 25)) is None
    bad = make_repo(tmp_path / "b", changelog=CHANGELOG.replace("2026-10-25", "2026-13-45"))
    assert guard.main(["--root", str(bad), "--tag", "v0.1.0"]) == 1
    assert "warning" not in capsys.readouterr().out
    assert guard.stale_date_warning(bad, "0.1.0", datetime.date(2026, 10, 25)) is None
    assert guard.stale_date_warning(stale, "9.9.9", datetime.date(2026, 10, 25)) is None
