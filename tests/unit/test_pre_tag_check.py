"""scripts/pre-tag-check.py: the owner's last check before a permanent tag.

A tag on an older commit would run that commit's older, unguarded release workflow, so the commit about to be tagged
must be the tip of main (or identical in .github and scripts) and must have been dry-run with build and attest green.
The git cases use a throwaway repository; `gh` is a fake."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pre-tag-check.py"
REPO = "owner/repo"

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _load():
    spec = importlib.util.spec_from_file_location("pre_tag_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ptc = _load()


def git(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *args],
        cwd=directory,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def commit(directory: Path, name: str, text: str) -> str:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(directory, "add", ".")
    git(directory, "commit", "-q", "-m", f"change {name}")
    return git(directory, "rev-parse", "HEAD")


@pytest.fixture
def clone(tmp_path):
    """A repository whose `origin/main` is its latest commit. Returns (path, [first, second, third])."""
    root = tmp_path / "clone"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    shas = [
        commit(root, ".github/workflows/publish-core.yml", "v1"),
        commit(root, "scripts/check.py", "v1"),
        commit(root, "README.md", "docs"),
    ]
    git(root, "update-ref", "refs/remotes/origin/main", shas[-1])
    return root, shas


class _Done:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class FakeGh:
    def __init__(self, runs=None, jobs=None, list_error=None, view_error=None, garbage=False):
        self.runs = runs if runs is not None else []
        self.jobs = jobs or {}  # run id -> {job name: conclusion}
        self.list_error, self.view_error, self.garbage = list_error, view_error, garbage
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str):
        self.calls.append(args)
        if args[:2] == ("run", "list"):
            if self.list_error:
                return _Done(1, "", self.list_error)
            return _Done(0, "{nope" if self.garbage else json.dumps(self.runs))
        if args[:2] == ("run", "view"):
            if self.view_error:
                return _Done(1, "", self.view_error)
            names = self.jobs.get(int(args[2]), {})
            return _Done(
                0,
                "[1]"
                if self.garbage
                else json.dumps({"jobs": [{"name": n, "conclusion": c} for n, c in names.items()]}),
            )
        raise AssertionError(args)


def green(sha: str, run_id: int = 11) -> FakeGh:
    return FakeGh(
        runs=[{"databaseId": run_id, "headSha": sha}], jobs={run_id: {"build": "success", "attest": "success"}}
    )


def run_main(monkeypatch, root, sha, fake, *extra):
    monkeypatch.setattr(ptc, "gh", fake)
    return ptc.main(["--sha", sha, "--repo", REPO, "--root", str(root), *extra])


@needs_git
def test_the_tip_of_main_with_a_green_attested_dry_run_is_safe_to_tag(clone, monkeypatch, capsys):
    root, shas = clone
    fake = green(shas[-1])
    assert run_main(monkeypatch, root, shas[-1], fake, "--tag", "v0.1.0") == 0
    out = capsys.readouterr().out
    assert f"ok: {shas[-1][:12]} is the tip of origin/main" in out
    assert f"https://github.com/{REPO}/actions/runs/11 built {shas[-1][:12]}: build and attest green" in out
    assert f"safe to tag: git tag -a v0.1.0 {shas[-1]} -m <message>, then git push origin v0.1.0" in out
    listing = fake.calls[0]
    for flag in (
        "--workflow",
        "publish-core.yml",
        "--event",
        "workflow_dispatch",
        "--branch",
        "main",
        "--status",
        "success",
    ):
        assert flag in listing


@needs_git
def test_an_older_commit_is_refused_when_the_release_machinery_differs(clone, monkeypatch, capsys):
    root, shas = clone
    assert run_main(monkeypatch, root, shas[0], green(shas[0])) == 1
    out = capsys.readouterr().out
    assert "is older than the tip of origin/main" in out and "would run THAT commit's older release workflow" in out
    assert "NOT safe to tag" in out


@needs_git
def test_an_older_commit_with_identical_workflows_and_scripts_is_allowed_with_a_note(clone, monkeypatch, capsys):
    root, shas = clone
    newer = commit(root, "README.md", "more docs")
    git(root, "update-ref", "refs/remotes/origin/main", newer)
    assert run_main(monkeypatch, root, shas[-1], green(shas[-1])) == 0
    out = capsys.readouterr().out
    assert "has moved on" in out and ".github and scripts are identical" in out


@needs_git
def test_a_commit_that_is_not_on_main_is_refused(clone, monkeypatch, capsys):
    root, shas = clone
    git(root, "switch", "-q", "-c", "feature")
    stray = commit(root, "README.md", "unreviewed")
    assert run_main(monkeypatch, root, stray, green(stray)) == 1
    assert "is not on origin/main" in capsys.readouterr().out


@needs_git
@pytest.mark.parametrize("sha", ["main", "HEAD", "abc1234", "A" * 40, ""])
def test_only_a_full_lower_case_commit_id_is_accepted_and_github_is_not_asked_about_anything_else(
    clone, monkeypatch, capsys, sha
):
    root, _ = clone
    fake = green("0" * 40)
    assert run_main(monkeypatch, root, sha, fake) == 1
    assert "--sha must be a full 40-character commit id" in capsys.readouterr().out
    assert fake.calls == []


@needs_git
def test_a_commit_that_is_not_in_this_clone_says_to_fetch(clone, monkeypatch, capsys):
    root, _ = clone
    assert run_main(monkeypatch, root, "1" * 40, green("1" * 40)) == 1
    assert "is not in this clone: run `git fetch origin` first" in capsys.readouterr().out


@needs_git
def test_a_clone_without_origin_main_says_to_fetch(clone, monkeypatch, capsys):
    root, shas = clone
    git(root, "update-ref", "-d", "refs/remotes/origin/main")
    assert run_main(monkeypatch, root, shas[-1], green(shas[-1])) == 1
    assert "origin/main is not known here" in capsys.readouterr().out


@needs_git
def test_a_dry_run_on_another_commit_does_not_count(clone, monkeypatch, capsys):
    root, shas = clone
    fake = FakeGh(runs=[{"databaseId": 5, "headSha": shas[0]}], jobs={5: {"build": "success", "attest": "success"}})
    assert run_main(monkeypatch, root, shas[-1], fake) == 1
    out = capsys.readouterr().out
    assert f"no successful dry run of publish-core.yml on main built {shas[-1][:12]}" in out and "-f attest=true" in out


@needs_git
@pytest.mark.parametrize(
    ("jobs", "words"),
    [
        ({"build": "success"}, "attest was not run"),
        ({"build": "success", "attest": "skipped"}, "attest was skipped"),
        ({"build": "success", "attest": "failure"}, "attest was failure"),
        ({"build": "failure", "attest": "success"}, "build was failure"),
        ({}, "build was not run, attest was not run"),
    ],
)
def test_a_dry_run_without_green_build_and_attest_jobs_does_not_count(clone, monkeypatch, capsys, jobs, words):
    root, shas = clone
    fake = FakeGh(runs=[{"databaseId": 7, "headSha": shas[-1]}], jobs={7: jobs})
    assert run_main(monkeypatch, root, shas[-1], fake) == 1
    out = capsys.readouterr().out
    assert words in out and "run it again with -f attest=true" in out


@needs_git
def test_any_green_attested_dry_run_of_the_commit_is_enough(clone, monkeypatch, capsys):
    root, shas = clone
    fake = FakeGh(
        runs=[{"databaseId": 9, "headSha": shas[-1]}, {"databaseId": 8, "headSha": shas[-1]}],
        jobs={9: {"build": "success"}, 8: {"build": "success", "attest": "success"}},
    )
    assert run_main(monkeypatch, root, shas[-1], fake) == 0
    assert "runs/8 built" in capsys.readouterr().out


@needs_git
@pytest.mark.parametrize(
    "fake",
    [
        FakeGh(list_error="HTTP 401"),
        FakeGh(garbage=True),
        FakeGh(runs=[{"databaseId": 3, "headSha": "X"}], view_error="HTTP 500"),
    ],
)
def test_a_github_that_cannot_answer_is_a_refusal_not_a_pass(clone, monkeypatch, capsys, fake):
    root, shas = clone
    fake.runs = fake.runs or [{"databaseId": 3, "headSha": shas[-1]}]
    for run in fake.runs:
        run["headSha"] = shas[-1]
    assert run_main(monkeypatch, root, shas[-1], fake) == 1
    assert "NOT safe to tag" in capsys.readouterr().out


@needs_git
def test_unreadable_job_lists_are_reported(clone, monkeypatch, capsys):
    root, shas = clone
    fake = FakeGh(runs=[{"databaseId": 3, "headSha": shas[-1]}], garbage=True)
    fake.garbage = False

    def view(*args):
        return _Done(0, "[1]") if args[:2] == ("run", "view") else FakeGh.__call__(fake, *args)

    assert run_main(monkeypatch, root, shas[-1], view) == 1
    assert "could not read its jobs" in capsys.readouterr().out


@needs_git
def test_the_tag_must_be_well_formed_and_unused(clone, monkeypatch, capsys):
    root, shas = clone
    assert run_main(monkeypatch, root, shas[-1], green(shas[-1]), "--tag", "v0.1") == 1
    assert "is not v followed by X.Y.Z" in capsys.readouterr().out
    git(root, "tag", "-a", "v0.1.0", shas[0], "-m", "old")
    assert run_main(monkeypatch, root, shas[-1], green(shas[-1]), "--tag", "v0.1.0") == 1
    assert "the tag v0.1.0 already exists in this clone" in capsys.readouterr().out
    assert run_main(monkeypatch, root, shas[-1], green(shas[-1]), "--tag", "v0.1.1") == 0


@needs_git
def test_a_directory_that_is_not_a_clone_is_a_refusal(tmp_path, monkeypatch, capsys):
    assert run_main(monkeypatch, tmp_path, "1" * 40, green("1" * 40), "--tag", "v0.1.0") == 1
    out = capsys.readouterr().out
    assert "is not in this clone" in out and "could not look up the tag v0.1.0" in out


def test_commands_that_hang_are_cut_off(monkeypatch):
    def hang(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(ptc.subprocess, "run", hang)
    cut = ptc.gh("run", "list")
    assert cut.returncode == 124 and "did not answer" in cut.stderr
    seen = {}

    def fine(command, **kwargs):
        seen.update(command=command, kwargs=kwargs)
        return _Done(0, "ok")

    monkeypatch.setattr(ptc.subprocess, "run", fine)
    assert ptc.gh("run", "list").stdout == "ok" and seen["command"] == ["gh", "run", "list"]
    assert seen["kwargs"]["timeout"] == ptc.TIMEOUT_SECONDS and not seen["kwargs"].get("shell")
    ptc.git(ROOT, "status")
    assert seen["command"] == ["git", "status"]


@needs_git
def test_it_runs_as_a_program_and_refuses_without_arguments():
    result = subprocess.run([sys.executable, "-I", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert result.returncode == 2 and "--sha" in result.stderr
