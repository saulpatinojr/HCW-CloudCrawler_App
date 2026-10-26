"""A saved Terraform state or plan can hold secrets, so `.gitignore` keeps them out of the repository (ticket #54, F10).

The fixtures under `samples/terraform/` are fictional and are named so that no ignore rule matches them
(`*.state.json`, `*.plan.json`); a real `terraform.tfstate`, a `terraform show -json` saved as `*.tfstate.json` and a
saved plan (`*.tfplan`, `*.tfplan.json`) are all ignored.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RULES = ["*.tfstate", "*.tfstate.*", "*.tfstate.json", "*.tfplan", "*.tfplan.json"]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("git and a checkout are needed")
    return subprocess.run([git, *args], cwd=ROOT, capture_output=True, text=True, check=False)  # noqa: S603  # nosec B603


def test_the_ignore_file_keeps_saved_states_and_plans_out():
    rules = {line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert set(RULES) <= rules


@pytest.mark.parametrize(
    "name",
    [
        "terraform.tfstate",
        "terraform.tfstate.backup",
        "prod.tfstate.json",
        "plan.tfplan",
        "plan.tfplan.json",
        "x/y/main.tfplan.json",
    ],
)
def test_a_saved_state_or_plan_is_ignored(name):
    assert _git("check-ignore", "-q", name).returncode == 0, name


@pytest.mark.parametrize(
    "name", ["samples/terraform/sample-estate.state.json", "samples/terraform/sample-estate.plan.json"]
)
def test_the_fictional_fixtures_are_not_ignored(name):
    assert _git("check-ignore", "-q", name).returncode == 1, name


def test_no_tracked_file_matches_an_ignore_rule():
    listed = _git("ls-files", "--cached", "--ignored", "--exclude-standard")
    assert listed.stdout.strip() == "", listed.stdout
