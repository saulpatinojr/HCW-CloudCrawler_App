"""scripts/check-release-version.py: the permanent guard that a release tag, every package version, the changelog and
the built files agree. A v* tag cannot be moved or deleted (ruleset "Protect release tags"), so these cases are the
only chance to catch a wrong one. No network; the git cases build a throwaway repository."""

from __future__ import annotations

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
