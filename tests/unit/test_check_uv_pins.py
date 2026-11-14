"""scripts/check_uv_pins.py, the check that every workflow uses the uv named by UV_VERSION in ci.yml.

Each case builds a small made-up repository in tmp_path, changes one thing, and runs the script as ci.yml runs it (a
separate Python, the standard library only). A last test runs it on this repository with the file list ci.yml gives it.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_uv_pins.py"
REQUIRED = [".github/workflows/security.yml", ".github/workflows/dependabot-lockfiles.yml"]

CI = """name: ci
on: push
permissions:
  contents: read
env:
  UV_VERSION: "0.13.8"
  PYTHON_VERSION: "3.15"
jobs:
  lint:
    runs-on: ubuntu-26.04
    steps:
      - run: python -m pip install "uv==${UV_VERSION}"
      - run: uv sync --frozen
"""
SECURITY = """name: security
on: push
permissions:
  contents: read
jobs:
  audit:
    runs-on: ubuntu-26.04
    steps:
      - run: python -m pip install "uv==0.13.8"
      - run: uv run pip-audit
  sbom:
    runs-on: ubuntu-26.04
    steps:
      - run: python -m pip install "uv==0.13.8"
"""
DEPENDABOT = """name: dependabot-lockfiles
on: pull_request
permissions:
  contents: read
env:
  UV_VERSION: "0.13.8"
jobs:
  export:
    runs-on: ubuntu-26.04
    steps:
      - run: python -m pip install "uv==${UV_VERSION}"
"""
OTHER = """name: other
on: push
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-26.04
    steps:
      - run: echo build
"""
ACTION = """name: self-merging-pr
runs:
  using: composite
  steps:
    - run: gh pr create --fill
      shell: bash
"""
W = ".github/workflows/"
OTHER_FILE = W + "other.yml"
ACTION_FILE = ".github/actions/self-merging-pr/action.yml"


def tree(root: Path) -> None:
    files = {
        W + "ci.yml": CI,
        W + "security.yml": SECURITY,
        W + "dependabot-lockfiles.yml": DEPENDABOT,
        OTHER_FILE: OTHER,
        ACTION_FILE: ACTION,
    }
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")


def run(root: Path, required: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, "-I", str(SCRIPT), *(REQUIRED if required is None else required), "--root", str(root)]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def append(rel: str, line: str) -> Callable[[Path], None]:
    def change(root: Path) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    return change


def replace(rel: str, old: str, new: str, count: int = -1) -> Callable[[Path], None]:
    def change(root: Path) -> None:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        assert old in text
        path.write_text(text.replace(old, new, count), encoding="utf-8")

    return change


def second_pin_only(root: Path) -> None:
    path = root / W / "security.yml"
    first, rest = path.read_text(encoding="utf-8").split('"uv==0.13.8"', 1)
    path.write_text(first + '"uv==0.13.8"' + rest.replace('"uv==0.13.8"', '"uv==0.13.7"'), encoding="utf-8")


def delete(rel: str) -> Callable[[Path], None]:
    return lambda root: (root / rel).unlink()


STEP = "      - run: "
FAILS: dict[str, tuple[Callable[[Path], None], str]] = {
    # change, and the file the error must name
    "a listed workflow pins another uv": (replace(W + "security.yml", "uv==0.13.8", "uv==0.13.7"), "security.yml"),
    "only the second pin of a listed workflow": (second_pin_only, "security.yml"),
    "a listed workflow is deleted": (delete(W + "security.yml"), "security.yml"),
    "a listed workflow installs no uv": (
        replace(W + "security.yml", 'python -m pip install "uv==0.13.8"', "echo no uv"),
        "security.yml",
    ),
    "UV_VERSION in a listed workflow's env": (
        replace(W + "dependabot-lockfiles.yml", 'UV_VERSION: "0.13.8"', 'UV_VERSION: "0.13.7"'),
        "dependabot-lockfiles.yml",
    ),
    "UV_VERSION in flow style": (append(OTHER_FILE, '    env: { UV_VERSION: "0.13.7" }'), "other.yml"),
    "UV_VERSION unquoted": (append(OTHER_FILE, "  UV_VERSION: 0.13.7"), "other.yml"),
    "UV_VERSION single-quoted": (append(OTHER_FILE, "  UV_VERSION: '0.13.7'"), "other.yml"),
    "UV_VERSION with a quoted key": (append(OTHER_FILE, '    env: { "UV_VERSION": "0.13.7" }'), "other.yml"),
    "UV_VERSION from an expression": (append(OTHER_FILE, "  UV_VERSION: ${{ vars.UV }}"), "other.yml"),
    "UV_VERSION exported in a script": (append(OTHER_FILE, "          export UV_VERSION=0.13.7"), "other.yml"),
    "UV_VERSION written to GITHUB_ENV": (
        append(OTHER_FILE, '          echo "UV_VERSION=0.13.7" >> "$GITHUB_ENV"'),
        "other.yml",
    ),
    "a new .yaml workflow": (append(W + "new.yaml", STEP + 'python -m pip install "uv==0.13.7"'), "new.yaml"),
    "a workflow in a subfolder": (append(W + "sub/deeper.yml", STEP + 'pip install "uv==0.13.7"'), "deeper.yml"),
    "a composite action": (append(ACTION_FILE, '    - run: python -m pip install "uv==0.13.7"'), "action.yml"),
    "a nested composite action": (
        append(".github/actions/team/release/action.yml", '    - run: pip install "uv==0.13.7"'),
        "team/release/action.yml",
    ),
    "a composite action named action.yaml": (
        append(".github/actions/other/action.yaml", '    - run: pip install "uv==0.13.7"'),
        "other/action.yaml",
    ),
    "pip install uv with no version": (append(OTHER_FILE, STEP + "python -m pip install uv"), "other.yml"),
    "pip install --upgrade 'uv'": (append(OTHER_FILE, STEP + "pip install --upgrade 'uv'"), "other.yml"),
    "pip3 install UV": (append(OTHER_FILE, STEP + "pip3 install UV"), "other.yml"),
    "pipx install uv": (append(OTHER_FILE, STEP + "pipx install uv"), "other.yml"),
    "uv tool install uv": (append(OTHER_FILE, STEP + "uv tool install uv"), "other.yml"),
    "uv pip install uv": (append(OTHER_FILE, STEP + "uv pip install uv"), "other.yml"),
    "uv>=0.13": (append(OTHER_FILE, STEP + 'pip install "uv>=0.13"'), "other.yml"),
    "uv<=0.13.8": (append(OTHER_FILE, STEP + 'pip install "uv<=0.13.8"'), "other.yml"),
    "uv~=0.13.8, the right number with another operator": (
        append(OTHER_FILE, STEP + 'pip install "uv~=0.13.8"'),
        "other.yml",
    ),
    "uv!=0.13.7": (append(OTHER_FILE, STEP + 'pip install "uv!=0.13.7"'), "other.yml"),
    "uv===0.13.7": (append(OTHER_FILE, STEP + 'pip install "uv===0.13.7"'), "other.yml"),
    "uv===0.13.8, the right number with another operator": (
        append(OTHER_FILE, STEP + 'pip install "uv===0.13.8"'),
        "other.yml",
    ),
    "uv == 0.13.7 after pip install": (append(OTHER_FILE, STEP + 'pip install "uv == 0.13.7"'), "other.yml"),
    "uv == 0.13.7 in a requirements line": (
        append(OTHER_FILE, '          echo "uv == 0.13.7" > req.txt'),
        "other.yml",
    ),
    "UV==0.13.7": (append(OTHER_FILE, STEP + 'pip install "UV==0.13.7"'), "other.yml"),
    "uv[x]==0.13.7": (append(OTHER_FILE, STEP + 'pip install "uv[x]==0.13.7"'), "other.yml"),
    "Uv[foo.bar]==0.13.7": (append(OTHER_FILE, STEP + 'pip install "Uv[foo.bar]==0.13.7"'), "other.yml"),
    "uvx uv@0.13.7": (append(OTHER_FILE, STEP + "uvx uv@0.13.7 --version"), "other.yml"),
    "uv==${{ env.UV_VERSION }}": (append(OTHER_FILE, STEP + 'pip install "uv==${{ env.UV_VERSION }}"'), "other.yml"),
    "astral-sh/setup-uv": (
        append(OTHER_FILE, "      - uses: astral-sh/setup-uv@0000000000000000000000000000000000000000 # v7"),
        "other.yml",
    ),
    "the uv image at another tag": (
        append(OTHER_FILE, STEP + "docker run --rm ghcr.io/astral-sh/uv:0.13.7 --version"),
        "other.yml",
    ),
    "uv==${UV_VERSION} in a file that sets none": (
        append(OTHER_FILE, STEP + 'pip install "uv==${UV_VERSION}"'),
        "other.yml",
    ),
    "$UV_VERSION in a file that sets none": (append(OTHER_FILE, STEP + 'echo "$UV_VERSION"'), "other.yml"),
    "ci.yml without UV_VERSION": (replace(W + "ci.yml", '  UV_VERSION: "0.13.8"\n', ""), "ci.yml"),
}

PASSES: dict[str, Callable[[Path], None]] = {
    "the tree as built": lambda root: None,
    "another correct pin": append(OTHER_FILE, STEP + 'pip install "uv==0.13.8"'),
    "uv[x]==0.13.8, the right uv with an extra": append(OTHER_FILE, STEP + 'pip install "uv[x]==0.13.8"'),
    "${UV_VERSION} in a file that sets it": append(
        W + "set.yml",
        'env:\n  UV_VERSION: "0.13.8"\njobs:\n  j:\n    steps:\n      - run: pip install "uv==${UV_VERSION}"',
    ),
    "pyuv==1.0": append(OTHER_FILE, STEP + 'pip install "pyuv==1.0"'),
    "uvicorn==0.30": append(OTHER_FILE, STEP + 'pip install "uvicorn==0.30"'),
    "uv-dynamic-versioning==0.8": append(OTHER_FILE, STEP + 'pip install "uv-dynamic-versioning==0.8"'),
    # pip refuses `uv_==…` (a requirement name must end in a letter or digit), so it installs nothing and is not uv.
    "uv_==0.13.7, not a name pip accepts": append(OTHER_FILE, STEP + 'pip install "uv_==0.13.7"'),
    "uv commands": append(OTHER_FILE, STEP + "uv sync --frozen && uv run pytest && uv lock --check"),
    "shell redirection after uv": append(OTHER_FILE, STEP + "echo uv > tool.txt"),
    "setup-uv named in a comment": append(OTHER_FILE, "# astral-sh/setup-uv is pinned nowhere in scope"),
    "the uv image at this tag": append(OTHER_FILE, STEP + "docker run --rm ghcr.io/astral-sh/uv:0.13.8 --version"),
    "pip installs another package": append(OTHER_FILE, STEP + "pipx install --python python3.15 checkov==3.3.30"),
}


@pytest.mark.parametrize("case", sorted(FAILS))
def test_a_change_to_another_uv_fails(tmp_path: Path, case: str) -> None:
    change, named = FAILS[case]
    tree(tmp_path)
    change(tmp_path)
    result = run(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    errors = [line for line in result.stdout.splitlines() if line.startswith("::error")]
    assert errors, result.stdout
    assert any(named in line for line in errors), result.stdout


@pytest.mark.parametrize("case", sorted(PASSES))
def test_the_same_uv_everywhere_passes(tmp_path: Path, case: str) -> None:
    tree(tmp_path)
    PASSES[case](tmp_path)
    result = run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::error" not in result.stdout


def test_an_error_names_the_line(tmp_path: Path) -> None:
    tree(tmp_path)
    second_pin_only(tmp_path)
    line = 1 + next(
        n for n, text in enumerate((tmp_path / W / "security.yml").read_text().splitlines()) if "0.13.7" in text
    )
    assert f"::error file=.github/workflows/security.yml,line={line}::" in run(tmp_path).stdout


def test_ci_runs_the_check_on_this_repository_and_it_passes() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    calls = re.findall(r"(?m)^\s*run: python scripts/check_uv_pins\.py (.+)$", ci)
    assert len(calls) == 1, "ci.yml runs scripts/check_uv_pins.py once, with the workflows that must install uv"
    required = shlex.split(calls[0])
    assert required and all((ROOT / rel).is_file() for rel in required), required
    result = run(ROOT, required)
    assert result.returncode == 0, result.stdout + result.stderr
