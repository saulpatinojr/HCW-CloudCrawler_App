"""Every workflow and composite action uses the one uv named by UV_VERSION in ci.yml (HCW-HybridCloudWorks#1707).

Run from the repository root by the `lint` job of ci.yml, before uv is installed, so it uses the standard library only:

    python scripts/check_uv_pins.py <workflow that must install that uv> ...

Each listed file must exist and install uv at UV_VERSION: a `pip`, `pip3`, `python -m pip`, `pipx`, `uv pip` or
`uv tool` install command in a `run:` script (its value on the same line, or a line of its `run: |` block), outside a
comment, with `uv==<version>` or `uv==${UV_VERSION}` as an argument; the second form counts only in a file that sets
UV_VERSION outside a comment (a YAML key, block or flow, or a shell assignment, `export` or a GITHUB_ENV write). Text
that only mentions the requirement (`echo "uv==…"`, a comment) installs nothing. Then every `*.yml` and `*.yaml` under
.github/workflows and every `action.yml` and `action.yaml` under .github/actions, at any depth, is read line by line,
comments included, and these fail:

- a uv requirement that is not `==` and exactly UV_VERSION: any operator (`===`, `~=`, `!=`, `>=`, `<=`, `<`, `>`,
  `@`), any spacing, any extras, and the name in any case or spelling that pip reads as uv (PEP 503: `UV`, `Uv`);
- pip, pipx, `uv pip` or `uv tool` installing uv with no version;
- `uses:` of the astral-sh/setup-uv action, and the ghcr.io/astral-sh/uv image at another tag;
- UV_VERSION given another value, in YAML (block, flow, quoted or not) or in a shell assignment (`export`, `X=`);
- `${UV_VERSION}`, `$UV_VERSION` or `env.UV_VERSION` in a file that never sets UV_VERSION.

Each problem is printed as a GitHub `::error` line; the exit code is 1 if there is one, 0 otherwise, 2 for bad usage.
What it cannot see: a version worked out while a job runs, or an install written in a way these patterns do not
describe. Other packages are left alone (`pyuv`, `uvicorn`, `uv-dynamic-versioning`).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CI = ".github/workflows/ci.yml"
NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
# A requirement: a name not glued to a longer name or a path, optional extras, an operator, then a version. A comparison
# needs a version that starts with a digit or `$`, so shell redirection (`echo uv > file`) is not read as one.
REQUIREMENT = re.compile(
    rf"(?<![A-Za-z0-9._/-])(?P<name>{NAME})\s*(?P<extras>\[[^\]]*\])?\s*"
    r"(?:(?P<op>===|==|~=|!=|>=|<=|<|>)\s*(?P<version>[0-9$][^\s\"'\\,;)\]]*)|@\s*(?P<at>[^\s\"'\\,;)\]]+))"
)
# An install command where a command starts: the start of a line (after a YAML `- run:` or `run:` key), or after
# `;`, `&`, `|`, `(`, `$(` or a backtick, optionally after `sudo` and `python -m`. So `echo 'pip install uv'` is text.
INSTALL = re.compile(
    r"(?:^\s*(?:-\s+)?(?:run:\s*)?|[;&|(`]\s*|\$\(\s*)(?:sudo\s+(?:-\S+\s+)*)?(?:python3?(?:\.\d+)?\s+-m\s+)?"
    r"(?:pip3?|pipx|uv\s+pip|uv\s+tool)\s+install\s+(?P<rest>.*)"
)
BARE = re.compile(rf"(?P<name>{NAME})(?:\[[^\]]*\])?")
SETUP_UV = re.compile(r"\buses:\s*[\"']?astral-sh/setup-uv\b", re.IGNORECASE)
UV_IMAGE = re.compile(r"astral-sh/uv:(?P<tag>[^\s\"'@]+)", re.IGNORECASE)
ASSIGN = re.compile(
    r"(?<![A-Za-z0-9_.${])[\"']?UV_VERSION[\"']?\s*(?::|=)\s*"
    r"(?:\"(?P<dq>[^\"]*)\"|'(?P<sq>[^']*)'|(?P<bare>[^\s,}#;\"']*))"
)
USE = re.compile(r"\$\{UV_VERSION\}|\$UV_VERSION\b|\benv\.UV_VERSION\b")
# UV_VERSION really set (read on the part of a line before a comment): a YAML key, block or flow, in any quoting; a
# shell assignment where a command starts or after `export`; or a line that writes it to GITHUB_ENV.
SETS = re.compile(
    r"^\s*(?:-\s+)?[\"']?UV_VERSION[\"']?\s*:(?:\s|$)"
    r"|[{,]\s*[\"']?UV_VERSION[\"']?\s*:"
    r"|(?:^|[;&|(]|\bexport)\s*UV_VERSION="
    r"|UV_VERSION=.*GITHUB_ENV"
)
# A `run:` key (`run:` or `- run:`) and its value on the same line.
RUN = re.compile(r"^(?P<lead>\s*(?:-\s+)?)run:(?:\s+(?P<value>.*))?$")
BLOCK = re.compile(r"[|>][-+0-9]*\s*(?:#.*)?")
SHELL_VAR = {"${UV_VERSION}", "$UV_VERSION"}


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def ci_uv_version(root: Path) -> str | None:
    """UV_VERSION from the top-level `env:` block of ci.yml."""
    in_env = False
    for line in (root / CI).read_text(encoding="utf-8").splitlines():
        if re.fullmatch(r"env:\s*(#.*)?", line):
            in_env = True
        elif in_env and line and not line[0].isspace():
            break
        elif in_env and (m := re.fullmatch(r"\s+UV_VERSION:\s*[\"']?([^\"'\s#]+)[\"']?\s*(#.*)?", line)):
            return m.group(1)
    return None


def scanned(root: Path) -> list[Path]:
    workflows = root / ".github" / "workflows"
    actions = root / ".github" / "actions"
    files = [p for pattern in ("*.yml", "*.yaml") for p in workflows.rglob(pattern)]
    files += [p for name in ("action.yml", "action.yaml") for p in actions.rglob(name)]
    return sorted(p for p in files if p.is_file())


def code(line: str) -> str:
    """The line up to its comment: a `#` that starts the line or follows a space, outside quotes (YAML and shell)."""
    quote = ""
    for i, ch in enumerate(line):
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i]
    return line


def script_lines(lines: list[str]) -> set[int]:
    """The numbers of the lines that are shell: a `run:` value on its own line, or a line of a `run: |` block."""
    found: set[int] = set()
    block_indent: int | None = None
    for n, line in enumerate(lines, 1):
        if block_indent is not None:
            if not line.strip() or len(line) - len(line.lstrip()) > block_indent:
                found.add(n)
                continue
            block_indent = None
        if m := RUN.match(line):
            value = (m["value"] or "").strip()
            if BLOCK.fullmatch(value):
                block_indent = len(m["lead"])
            elif value and not value.startswith("#"):
                found.add(n)
    return found


def check_file(path: Path, rel: str, want: str) -> tuple[list[str], bool]:
    """The problems in one file, and whether it installs uv at `want`."""
    lines = path.read_text(encoding="utf-8").splitlines()
    sets_var = any(SETS.search(code(line)) for line in lines)
    script = script_lines(lines)
    problems: list[str] = []
    installs = False

    def error(n: int, message: str) -> None:
        problems.append(f"::error file={rel},line={n}::{message}")

    for n, line in enumerate(lines, 1):
        for m in REQUIREMENT.finditer(line):
            if normalize(m["name"]) != "uv":
                continue
            version = m["version"] if m["version"] is not None else m["at"]
            op = m["op"] or "@"
            # Anywhere, comments included; whether it installs anything is read from the install commands below.
            if op == "==" and version in SHELL_VAR and not sets_var:
                error(n, f"{m.group(0)} uses UV_VERSION, which this file never sets")
            elif not (op == "==" and (version == want or version in SHELL_VAR)):
                error(n, f"{m.group(0)} is not uv=={want}")
        if m := INSTALL.search(code(line)):
            # A commented-out install installs nothing (Copilot on HCW-CloudAssessor_App#104). One command (up to
            # `;`, `&`, `|` or a comment), with spaces around an operator closed up (`uv == 1`).
            command = re.split(r"[;&|#]", m["rest"], maxsplit=1)[0]
            command = re.sub(r"\s*(===|==|~=|!=|>=|<=|<|>|@)\s*", r"\1", command).strip()
            for token in re.split(r"\s+", command):
                token = token.strip("\"'")
                if (
                    token
                    and not token.startswith("-")
                    and (b := BARE.fullmatch(token))
                    and normalize(b["name"]) == "uv"
                ):
                    error(n, f"installs {token} with no version; pin uv=={want}")
        if n in script and (m := INSTALL.search(code(line))):
            command = re.split(r"[;&|]", m["rest"], maxsplit=1)[0]
            command = re.sub(r"\s*(===|==|~=|!=|>=|<=|<|>|@)\s*", r"\1", command)
            for r in REQUIREMENT.finditer(command):
                version = r["version"]
                if normalize(r["name"]) == "uv" and r["op"] == "==":
                    installs = installs or version == want or (version in SHELL_VAR and sets_var)
        if SETUP_UV.search(line):
            error(n, f"astral-sh/setup-uv chooses its own uv; install uv=={want} with pip instead")
        for m in UV_IMAGE.finditer(line):
            if m["tag"] != want:
                error(n, f"{m.group(0)} is not uv {want}")
        for m in ASSIGN.finditer(line):
            value = next(v for v in (m["dq"], m["sq"], m["bare"]) if v is not None)
            if value != want:
                error(n, f"UV_VERSION is set to {value!r}, not {want}")
        if not sets_var and USE.search(line):
            error(n, "uses UV_VERSION, which this file never sets")
    return problems, installs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("required", nargs="+", help="workflow files (from the root) that must install uv at UV_VERSION")
    parser.add_argument("--root", type=Path, default=Path("."), help="repository root (default: the current folder)")
    args = parser.parse_args(argv)
    root: Path = args.root
    if not (root / CI).is_file():
        print(f"::error::{CI} not found under {root}")
        return 2
    want = ci_uv_version(root)
    if not want:
        print(f"::error file={CI}::no UV_VERSION in the top-level env block")
        return 1
    problems: list[str] = []
    installs: dict[str, bool] = {}
    for path in scanned(root):
        rel = path.relative_to(root).as_posix()
        found, installs[rel] = check_file(path, rel, want)
        problems += found
    for rel in args.required:
        if not (root / rel).is_file():
            problems.append(f"::error::{rel} is gone; update the list given to scripts/check_uv_pins.py in {CI}")
        elif rel not in installs:
            problems.append(f"::error file={rel}::is not a workflow or composite action this check reads")
        elif not installs[rel]:
            problems.append(f"::error file={rel}::does not install uv=={want}")
    for line in problems:
        print(line)
    if not problems:
        print(f"uv {want} everywhere: {len(installs)} files read, {len(args.required)} required installs found")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
