"""Every workflow step that runs Node.js or Python on the runner comes after the job chooses its version (#1707).

A job that runs `node`, `npm`, `npx`, `python`, `python3`, `pip`, `uv` or `uvx` without actions/setup-node or
actions/setup-python gets whatever the runner image ships: on ubuntu-26.04 in November 2026 that was Node.js 24 and
Python 3.14, both below the HCW floors (Node.js 26, Python 3.15; HCW-HybridCloudWorks issue #1707). `uv` and `uvx` count
as Python, because uv runs the interpreter it finds, the runner's own unless one was set up; so astral-sh/setup-uv
counts as setting Python up only when it is given a `python-version` at or above the floor. Nothing else would notice,
because a job that names no version has nothing for a version check to read. This is a port of the website's
`scripts/workflow-runtime-setup.test.mjs`.

A command counts when it is in command position on a line of a `run:` step: at the start, after `$(`, `<(`, a
backtick, `(`, `{`, `|`, `&&`, `||` or `;`, after leading `NAME=value` assignments (the value plain text, a quoted
string, or both run together), or after a word that runs the next one (`env`, `sudo`, `xargs`, `exec`, `time`, `!`,
`if`, `then`, `do` and the like). It does not count inside a quoted
string (unless a double-quoted string runs a command with `$(`, `<(` or a backtick), on a comment line, or as an
argument (`docker run image python ...`). The set-up step must come before the first such step. Limits, on purpose: a
job that runs in a `container:` uses that image's runtime and is not checked; a script or program a step calls is not
read, so a step that starts a runtime that way is listed in INDIRECT_RUNTIME; and a composite action is checked on its
own steps only, because the job that calls it is in another file.

A set-up step with its own `if:` may be skipped while a later command still runs on the runner's own interpreter
(Copilot on HCW-NetworkEyes_AddOn#100), so it covers a later step only when that step's `if:` is the same condition,
or is one of the terms the set-up's condition joins with a top-level `||` (whenever that step runs, so did the
set-up). Conditions are compared without a surrounding `${{ }}`, with runs of spaces made one, and a term without one
pair of parentheses around the whole of it. A set-up step with no `if:` covers every later step whose condition does
not test the job's status. A job's own `if:` does not matter here, because it decides whether every step of the job
runs, alike.

The job's status is compared on its own. Without `always()`, `failure()`, `cancelled()` or `success()` in it, a step's
condition includes an unwritten `success()`, so a set-up step with no `if:` is skipped once an earlier step has
failed, while a later `if: always()`, `failure()` or `!cancelled()` step still runs (Copilot on
HCW-CloudAssessor_App#97). So the statuses a later step can run under (after success, after a failure, after a
cancel) must all be ones its set-up step runs under too, and the rule above is applied to the conditions with their
status-only `&&` terms taken out.

Each set-up step must also ask for the floor or newer (Copilot on HCW-CloudCrawler_App#81): `python-version` or
`python-version-file`, `node-version` or `node-version-file`, read through `${{ env.X }}` (the step's, job's or
workflow's `env:`), `${{ matrix.X }}` (every entry of the job's matrix list) and the named file. A version that names a
line only (`26`, `3.15`) stands for that line's newest release, so it passes when the line is at or above the floor's;
an exact version (`26.10.0`) must be at or above the floor itself. A value this test cannot work out fails it, naming
the step, rather than passing unchecked.

The repository has no YAML library (see test_workflows.py), so the files are read by indentation; the last tests check
that the reader saw every step."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTIONS = ROOT / ".github" / "actions"

# Steps that use the runner's own interpreter on purpose, keyed "file > job > step name > runtime", each with a reason
# a reviewer can check. Keyed by step, not job, so a new step in the same job is still checked. Empty on 2026-11-12:
# every step that runs Node.js, Python or uv sets its version up first.
RUNNER_DEFAULT_ALLOWED: dict[str, str] = {}

# Steps that start a runtime indirectly, through a program the step runs, which the command check cannot see in the
# `run:` text. Each counts as running that runtime, so its set-up step must come first. Same keys, each with a reason.
INDIRECT_RUNTIME: dict[str, str] = {
    "ci.yml > contract > Azure MCP Server 3.0.0 tools/list matches the committed snapshot (ADR 0001) > node": (
        "the azmcp test starts Azure MCP Server 3.0.0 with npx (src/cloud_crawler_appliance/mcp_host/contract.py)"
    ),
    "ci.yml > lint > requirements.lock.txt matches uv.lock > python": (
        "`bash scripts/check-lockfiles.sh` runs scripts/export-lockfiles.sh, which runs `uv export`"
    ),
    "dependabot-lockfiles.yml > export > Regenerate the export from uv.lock > python": (
        "`bash scripts/export-lockfiles.sh` runs `uv export`"
    ),
}

# Where a command may start: the line's start or an opening/joining character, then any `NAME=value` assignments (the
# value plain text, a quoted string, or both run together: `FOO="a b"`) and words that run the next word
# (`env FOO=1 node`, `sudo node`, `if node ...; then`).
ASSIGNMENT = r"""[A-Za-z_][A-Za-z0-9_]*=(?:"(?:[^"\\]|\\.)*"|'[^']*'|[^\s"'])*\s+"""
START = (
    r"(?:^|[$<]\(\s*|`\s*|[({|;&]\s*)"
    r"(?:" + ASSIGNMENT + r"|(?:env|sudo|xargs|exec|time|nice|command|if|then|else|elif|do|while|until|!)\s+)*"
)
COMMAND = {
    "node": re.compile(START + r"(?:node|npm|npx)(?=\s|$)"),
    "python": re.compile(START + r"(?:python(?:3(?:\.\d+)?)?|pip3?|uvx?)(?=\s|$)"),
}
SETUP = {"node": re.compile(r"^actions/setup-node@"), "python": re.compile(r"^actions/setup-python@")}
# astral-sh/setup-uv sets Python up only when given a `python-version` (see `sets_up`).
SETUP_UV = re.compile(r"^astral-sh/setup-uv@")

# The lowest versions a set-up step may ask for. The program's floors are kept in scripts/version-floors.json in
# HCW-HybridCloudWorks; change them there first, then here.
PYTHON_FLOOR = (3, 15, 0)
NODE_FLOOR = (26, 11, 0)
FLOORS = {"python": PYTHON_FLOOR, "node": NODE_FLOOR}
# The job statuses a step can run after, and the status functions that name them.
STATUSES = {"success", "failure", "cancelled"}
STATUS_CALL = re.compile(r"(!?)\s*\b(always|failure|cancelled|success)\(\s*\)")
# The set-up step's inputs that name the version, directly or through a file in the repository.
VERSION_INPUTS = {"python": ("python-version", "python-version-file"), "node": ("node-version", "node-version-file")}


@dataclass
class Step:
    name: str | None = None
    uses: str = ""
    run: str = ""
    condition: str = ""  # the step's `if:`, as written
    inputs: dict[str, str] = field(default_factory=dict)  # its `with:`
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class Job:
    container: bool = False
    steps: list[Step] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)  # the workflow's `env:` with the job's own on top
    matrix: dict[str, list[str]] = field(default_factory=dict)


def without_quoted_text(line: str) -> str:
    """The line with the text of its quoted strings taken out, so words in a message (`echo "...; if pip named..."`)
    do not count. A double-quoted string that runs a command (`"$(node x)"`, or the older "`node x`") is kept. An
    escaped backtick (`\\``, as in Markdown written to the step summary) is a plain character, so it is dropped
    first."""
    line = re.sub(r"'[^']*'", "''", line.replace("\\`", ""))
    return re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: m.group(0) if re.search(r"[$<]\(|`", m.group(0)) else '""', line)


def runs_runtime(run: str, kind: str) -> bool:
    """True when a run step calls the runtime in command position on a line that is not a comment."""
    lines = (line.strip() for line in run.split("\n"))
    return any(COMMAND[kind].search(without_quoted_text(line)) for line in lines if line and not line.startswith("#"))


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _scalar(value: str) -> str:
    value = re.sub(r"\s+#.*$", "", value.strip()) if not value.strip().startswith(("'", '"')) else value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _flow_mapping(text: str) -> dict[str, str]:
    """A one-line `{ key: value, ... }` mapping, split on the commas outside quotes and `${{ }}`."""
    inner = text[text.index("{") + 1 : text.rindex("}")]
    parts, depth, quote, start = [], 0, "", 0
    for index, char in enumerate(inner):
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(inner[start:index])
            start = index + 1
    parts.append(inner[start:])
    pairs = (part.partition(":") for part in parts if part.strip())
    return {key.strip(): _scalar(value) for key, _, value in pairs}


def _block(lines: list[str], at: int, indent: int) -> list[str]:
    """The lines under the key on line `at` (at `indent` spaces), up to the next line at that indent or less."""
    block = []
    for line in lines[at + 1 :]:
        if line.strip() and not line.lstrip().startswith("#") and _indent(line) <= indent:
            break
        block.append(line)
    return block


def _mapping(lines: list[str], at: int, indent: int) -> dict[str, str]:
    """The mapping under the key on line `at`: a `{ ... }` on the same line, or the `key: value` lines below it."""
    rest = _scalar(lines[at].split(":", 1)[1])
    if rest.startswith("{"):
        return _flow_mapping(rest)
    block = _block(lines, at, indent)
    inner = min((_indent(line) for line in block if line.strip()), default=indent + 2)
    pairs = (re.match(rf"^ {{{inner}}}([A-Za-z0-9_.-]+):(.*)$", line) for line in block)
    return {m.group(1): _scalar(m.group(2)) for m in pairs if m}


def _matrix(lines: list[str], head: int, stop: int) -> dict[str, list[str]]:
    """The lists of a job's `strategy: matrix:`, each written `[a, b]` or as `- a` lines; {} when it has none."""
    at = next((i for i in range(head, stop) if re.match(r"^      matrix:\s*(#.*)?$", lines[i])), None)
    if at is None:
        return {}
    block = _block(lines, at, 6)
    found: dict[str, list[str]] = {}
    for index, line in enumerate(block):
        match = re.match(r"^        ([A-Za-z0-9_-]+):(.*)$", line)
        if not match:
            continue
        rest = _scalar(match.group(2))
        if rest.startswith("["):
            found[match.group(1)] = [_scalar(v) for v in rest.strip("[]").split(",") if v.strip()]
        else:
            items = _block(block, index, 8)
            found[match.group(1)] = [_scalar(i.strip()[2:]) for i in items if i.strip().startswith("- ")]
    return found


def _steps(lines: list[str], start: int, end: int) -> list[Step]:
    """The steps of the block list that begins after line `start` (a `steps:` key) and ends before line `end`."""
    items = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("- ")]
    if not items:
        return []
    dash = _indent(lines[items[0]])
    items = [i for i in items if _indent(lines[i]) == dash]
    found = []
    for n, first in enumerate(items):
        last = items[n + 1] if n + 1 < len(items) else end
        body = [" " * (dash + 2) + lines[first][dash + 2 :]] + lines[first + 1 : last]
        key_indent = dash + 2
        step = Step()
        i = 0
        while i < len(body):
            line = body[i]
            match = re.match(rf"^ {{{key_indent}}}([A-Za-z0-9_-]+):(.*)$", line)
            i += 1
            if not match:
                continue
            key, value = match.group(1), match.group(2)
            if key == "run" and re.match(r"^\s*[|>][-+0-9]*\s*(#.*)?$", value):
                block = []
                while i < len(body) and (not body[i].strip() or _indent(body[i]) > key_indent):
                    block.append(body[i])
                    i += 1
                step.run = "\n".join(block)
            elif key == "run":
                step.run = value.strip()
            elif key == "name":
                step.name = _scalar(value)
            elif key == "uses":
                step.uses = _scalar(value)
            elif key == "if":
                step.condition = _scalar(value)
            elif key in ("with", "env"):
                mapping = _mapping(body, i - 1, key_indent)
                i += len(_block(body, i - 1, key_indent))
                if key == "with":
                    step.inputs = mapping
                else:
                    step.env = mapping
        found.append(step)
    return found


def workflow_jobs(text: str) -> dict[str, Job]:
    """Each job of a workflow file: whether it runs in a container, and its steps in order."""
    lines = text.splitlines()
    try:
        top = lines.index("jobs:")
    except ValueError:
        return {}
    end = next((i for i in range(top + 1, len(lines)) if lines[i][:1] not in ("", " ", "#")), len(lines))
    heads = [i for i in range(top + 1, end) if re.match(r"^  [A-Za-z0-9_-]+:\s*(#.*)?$", lines[i])]
    top_env = next((i for i, line in enumerate(lines) if re.match(r"^env:", line)), None)
    workflow_env = _mapping(lines, top_env, 0) if top_env is not None else {}
    jobs = {}
    for n, head in enumerate(heads):
        stop = heads[n + 1] if n + 1 < len(heads) else end
        job = Job(container=any(re.match(r"^    container:", lines[i]) for i in range(head, stop)))
        env_at = next((i for i in range(head, stop) if re.match(r"^    env:", lines[i])), None)
        job.env = {**workflow_env, **(_mapping(lines, env_at, 4) if env_at is not None else {})}
        job.matrix = _matrix(lines, head, stop)
        steps_at = next((i for i in range(head, stop) if re.match(r"^    steps:\s*$", lines[i])), None)
        if steps_at is not None:
            job.steps = _steps(lines, steps_at, stop)
        jobs[lines[head].split(":", 1)[0].strip()] = job
    return jobs


def action_jobs(text: str) -> dict[str, Job]:
    """A composite action's steps, as one job named `(composite)`; any other kind of action has none."""
    lines = text.splitlines()
    if not any(re.match(r"^  using:\s*['\"]?composite", line) for line in lines):
        return {}
    steps_at = next(i for i, line in enumerate(lines) if re.match(r"^  steps:\s*$", line))
    end = next((i for i in range(steps_at + 1, len(lines)) if lines[i][:1] not in ("", " ", "#")), len(lines))
    return {"(composite)": Job(steps=_steps(lines, steps_at, end))}


def step_key(file: str, job: str, step: Step, i: int, kind: str) -> str:
    return f"{file} > {job} > {step.name or f'step {i + 1}'} > {kind}"


def _normalized(expression: str) -> str:
    """An `if:` expression without a surrounding `${{ }}` and with runs of spaces made one."""
    text = expression.strip()
    wrapped = re.fullmatch(r"\$\{\{(.*)\}\}", text, re.DOTALL)
    return " ".join((wrapped.group(1) if wrapped else text).split())


def _without_outer_parentheses(term: str) -> str:
    """The term without one pair of parentheses, when that pair encloses the whole of it."""
    if not (term.startswith("(") and term.endswith(")")):
        return term
    depth = 0
    for index, char in enumerate(term):
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth == 0 and index < len(term) - 1:
            return term
    return term[1:-1].strip()


def _top_level_terms(expression: str, operator: str = "||", unwrap: bool = True) -> list[str]:
    """The terms an expression joins with `||` (or `&&`) outside parentheses and quotes, each without one pair of
    parentheses around the whole of it (unless `unwrap` is false); a one-item list when there is no such operator."""
    terms, depth, quote, start, index = [], 0, "", 0, 0
    while index < len(expression):
        char = expression[index]
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and expression.startswith(operator, index):
            terms.append(expression[start:index])
            start = index + len(operator)
            index += len(operator) - 1
        index += 1
    terms.append(expression[start:])
    return [_without_outer_parentheses(term.strip()) if unwrap else term.strip() for term in terms]


def statuses(expression: str) -> set[str]:
    """The job statuses a step with this condition can run after: `success` alone when it names no status function
    (the unwritten `success()`), all three for `always()`, `success` and `failure` for `!cancelled()`, and so on."""
    found = STATUS_CALL.findall(expression)
    if not found:
        return {"success"}
    named = set()
    for negated, call in found:
        meant = STATUSES if call == "always" else {call}
        named |= (STATUSES - meant) if negated else meant
    return named


def _without_status(expression: str) -> str:
    """The condition without its top-level `&&` terms that test only the job's status (`always()`, `!cancelled()`)."""
    terms = _top_level_terms(expression, "&&", unwrap=False)
    kept = [term for term in terms if re.sub(r"[\s!()&|]", "", STATUS_CALL.sub("", term))]
    return expression if len(kept) == len(terms) else " && ".join(kept)


def covers(setup: Step, step: Step) -> bool:
    """True when a set-up step runs whenever the later step does: it runs after every job status the later step can
    run after, and, status terms aside, it has no `if:`, the same `if:`, or an `if:` whose top-level `||` terms
    include the later step's."""
    wanted, given = _normalized(step.condition), _normalized(setup.condition)
    if not statuses(wanted) <= statuses(given):
        return False
    wanted, given = _without_status(wanted), _without_status(given)
    return given in ("", wanted) or wanted in _top_level_terms(given, "||")


def unset_steps(file: str, jobs: dict[str, Job], indirect: dict[str, str] | None = None) -> list[str]:
    """The steps that run a runtime before (or without) setting it up: "file > job > step > runtime". A step needs an
    earlier set-up step that covers it (see `sets_up` and `covers`). A step named in `indirect` counts as running its
    runtime even when its `run:` text does not show it."""
    indirect = INDIRECT_RUNTIME if indirect is None else indirect
    found = []
    for name, job in jobs.items():
        if job.container:
            continue
        for kind in COMMAND:
            for i, step in enumerate(job.steps):
                key = step_key(file, name, step, i, kind)
                if not (runs_runtime(step.run, kind) or key in indirect):
                    continue
                if not any(sets_up(earlier, job, kind) and covers(earlier, step) for earlier in job.steps[:i]):
                    found.append(key)
    return found


def _resolved(value: str, step: Step, job: Job, depth: int = 0) -> list[str] | None:
    """The plain values an input stands for: itself, or what `${{ env.X }}` (the step's, job's or workflow's `env:`) or
    `${{ matrix.X }}` (every entry of the job's matrix list) holds. None when it cannot be worked out here."""
    found = re.fullmatch(r"\$\{\{\s*(env|matrix)\.([A-Za-z0-9_-]+)\s*\}\}", value.strip())
    if not found:
        return None if "${{" in value else [value.strip()]
    source, name = found.groups()
    if source == "env":
        env = {**job.env, **step.env}
        return _resolved(env[name], step, job, depth + 1) if name in env and depth < 5 else None
    return job.matrix.get(name) or None


def is_set_up(step: Step, kind: str) -> bool:
    """True for a step that sets the runtime up: actions/setup-node or actions/setup-python, or, for Python,
    astral-sh/setup-uv given a `python-version`."""
    if kind == "python" and SETUP_UV.search(step.uses):
        return "python-version" in step.inputs
    return bool(SETUP[kind].search(step.uses))


def sets_up(step: Step, job: Job, kind: str, root: Path = ROOT) -> bool:
    """True when the step chooses the runtime for the steps after it. setup-uv counts only with a `python-version` at
    or above the floor (a lower one is also reported by the floor test); without one uv uses the runner's Python."""
    if not is_set_up(step, kind):
        return False
    if not SETUP_UV.search(step.uses):
        return True
    versions = requested_versions(step, job, kind, root)
    return bool(versions) and all(_below_floor(version, kind) is False for version in versions)


def requested_versions(step: Step, job: Job, kind: str, root: Path = ROOT) -> list[str] | None:
    """The versions a set-up step asks for, read through `env`, `matrix` and a version file; None when unreadable."""
    direct, from_file = VERSION_INPUTS[kind]
    if direct in step.inputs:
        return _resolved(step.inputs[direct], step, job)
    if from_file not in step.inputs:
        return None
    paths = _resolved(step.inputs[from_file], step, job) or []
    if len(paths) != 1 or not (root / paths[0]).is_file():
        return None
    lines = (line.strip() for line in (root / paths[0]).read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")] or None


def _below_floor(version: str, kind: str) -> bool | None:
    """True when the version is under the floor, False when at or above it, None when it is not a version number. A
    version that names a line only (`26`, `3.15`, `26.x`) means that line's newest release, so only its numbers are
    compared with the floor's (`26` with 26, `3.15` with 3.15); an exact one (`26.10.0`) is compared in full."""
    found = re.match(r"v?(\d+(?:\.\d+)*)", version.strip())
    if not found:
        return None
    numbers = tuple(int(number) for number in found.group(1).split("."))[:3]
    return numbers < FLOORS[kind][: len(numbers)]


def floor_problems(file: str, jobs: dict[str, Job], root: Path = ROOT) -> list[str]:
    """Every set-up step that asks for a version below the floor, or one this test cannot read, with the reason."""
    problems = []
    for name, job in jobs.items():
        for i, step in enumerate(job.steps):
            for kind in COMMAND:
                if not is_set_up(step, kind):
                    continue
                label = step_key(file, name, step, i, kind)
                versions = requested_versions(step, job, kind, root)
                if not versions:
                    problems.append(f"{label}: cannot work out the version it asks for")
                for version in versions or []:
                    below = _below_floor(version, kind)
                    if below is None:
                        problems.append(f"{label}: {version!r} is not a version number this test can compare")
                    elif below:
                        problems.append(f"{label}: asks for {version}, below the floor")
    return problems


def every_file() -> dict[str, tuple[str, dict[str, Job]]]:
    files = {}
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        files[path.name] = (text, workflow_jobs(text))
    for path in sorted(ACTIONS.glob("*/action.y*ml")):
        text = path.read_text(encoding="utf-8")
        files[path.relative_to(ROOT / ".github").as_posix()] = (text, action_jobs(text))
    return files


@pytest.mark.parametrize(
    "line",
    [
        "token=$(node scripts/github-app-token.mjs)",
        "npm ci --no-audit",
        "FOO=1 node x",
        "env FOO=1 node x",
        "sudo node x",
        "xargs node x",
        "diff a <(node x)",
        "(node x)",
        "{ node x; }",
        "if node x; then",
        "! node x",
        "time node x",
        "exec node x",
        "cd y && npm ci",
        "a || npx b",
        "env FOO='bar baz' node x.js",
        "FOO=\"a b\"'c d'e node x.js",
        'token="$(node scripts/github-app-token.mjs)"',
        'echo "`node --version`"',
    ],
)
def test_node_in_command_position_counts(line):
    assert runs_runtime(line, "node")


@pytest.mark.parametrize(
    "line",
    [
        "cat x | python3 -I check.py",
        "python3.15 -I x.py",
        "python -m pip install uv",
        "pip install x",
        "uv sync --frozen --all-packages",
        "uvx zizmor .github",
        "set -e; uv run pytest",
        'python -m pip install "uv==0.11.32"',
        "version=`python3 scripts/check.py`",
        'echo "`python3 --version`"',
        'FOO="bar baz" python3 check.py',
        'STAMP="$(date +%s) run" python3 check.py',
        "uv run python scripts/check.py",
    ],
)
def test_python_and_uv_in_command_position_count(line):
    assert runs_runtime(line, "python")


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        ('echo "run \\`node scripts/x.mjs\\` by hand"', "node"),
        ("# node is not run here", "node"),
        ("for node in items:", "node"),
        ('echo "$NODE_VERSION"', "node"),
        ("nodes=3 nodejs-check", "node"),
        ('docker run --rm img python -c "import azure"', "python"),
        ("if docker run --rm img python -m pip --version; then", "python"),
        ("/opt/az/bin/python3 -Im pip check", "python"),
        ('echo "the stage is wrong; if pip named the file differently, look"', "python"),
        ("echo 'then uv sync'", "python"),
        ("uvicorn app:main", "python"),
        ("bash scripts/export-lockfiles.sh", "python"),
        ("echo 'literal `python3` text'", "python"),
        ('FOO="python3 x" true', "python"),
    ],
)
def test_text_arguments_and_comments_do_not_count(line, kind):
    assert not runs_runtime(line, kind)


SAMPLE = """\
name: sample
on: push
jobs:
  late:
    runs-on: ubuntu-26.04
    steps:
      - name: Early
        run: node a.mjs
      - uses: actions/setup-node@abc # v7
  none:
    steps:
      - run: |
          set -e
          # python3 is only named in this comment
          echo "python3 is only named in this string"
          python3 b.py
  uv-only:
    steps:
      - uses: astral-sh/setup-uv@abc
      - name: "Run"
        run: uv sync
  good:
    steps:
      - uses: actions/setup-python@abc
        with: { python-version: "3.15" }
      - name: Install
        run: python -m pip install "uv==0.11.32"
      - uses: actions/setup-node@abc
      - run: >-
          npx something
  boxed:
    container: node:26
    steps:
      - run: node a.mjs
"""


def test_jobs_that_set_up_late_or_not_at_all_are_found():
    jobs = workflow_jobs(SAMPLE)
    assert list(jobs) == ["late", "none", "uv-only", "good", "boxed"]
    assert unset_steps("x.yml", jobs) == [
        "x.yml > late > Early > node",
        "x.yml > none > step 1 > python",
        "x.yml > uv-only > Run > python",
    ]


CONDITIONS = """\
name: conditions
on: push
jobs:
  skipped:
    steps:
      - uses: actions/setup-python@abc
        if: false
      - name: Run
        run: python3 a.py
  same-condition:
    steps:
      - uses: actions/setup-python@abc
        if: ${{ !cancelled() }}
      - name: Run
        if: "!cancelled()"
        run: python3 a.py
  unconditional-setup:
    steps:
      - uses: actions/setup-python@abc
      - name: Run
        if: github.ref == 'refs/heads/main'
        run: python3 a.py
  after-a-failure:
    steps:
      - uses: actions/setup-python@abc
      - name: Run
        if: always()
        run: python3 a.py
  after-a-failure-set-up-too:
    steps:
      - uses: actions/setup-python@abc
        if: always()
      - name: Run
        if: failure()
        run: python3 a.py
  other-condition:
    steps:
      - uses: actions/setup-python@abc
        if: github.event_name == 'push'
      - name: Run
        if: failure()
        run: python3 a.py
  or-term:
    steps:
      - uses: actions/setup-node@abc
        if: matrix.relevant == 'true' || (matrix.name == 'scripts (operations)')
      - name: Run
        if: matrix.name == 'scripts (operations)'
        run: node a.mjs
  and-term:
    steps:
      - uses: actions/setup-node@abc
        if: matrix.relevant == 'true' && matrix.name == 'scripts'
      - name: Run
        if: matrix.name == 'scripts'
        run: node a.mjs
  job-condition:
    if: github.event_name == 'push'
    steps:
      - uses: actions/setup-node@abc
      - run: node a.mjs
"""


def test_a_set_up_step_with_its_own_condition_covers_only_steps_it_always_runs_before():
    assert unset_steps("x.yml", workflow_jobs(CONDITIONS), {}) == [
        "x.yml > skipped > Run > python",
        "x.yml > after-a-failure > Run > python",
        "x.yml > other-condition > Run > python",
        "x.yml > and-term > Run > node",
    ]


@pytest.mark.parametrize(
    ("setup", "step", "covered"),
    [
        ("${{  a &&   b }}", "a && b", True),
        ("a || b", "b", True),
        ("(a) || (b && c)", "b && c", True),
        ("x == 'p || q' || r", "x == 'p", False),
        ("(a || b) && c", "a", False),
        ("a || b", "a || c", False),
        ("", "anything", True),
        # The job's status: a set-up step with no `if:` runs only after success (the unwritten `success()`).
        ("", "", True),
        ("", "always()", False),
        ("", "${{ !cancelled() }}", False),
        ("", "failure()", False),
        ("${{ !cancelled() }}", "${{ !cancelled() }}", True),
        ("always()", "failure()", True),
        ("always()", "cancelled()", True),
        ("!cancelled()", "always()", False),
        ("!cancelled()", "cancelled()", False),
        ("failure()", "", False),
        ("always() && a", "a", True),
        ("always() && a", "!cancelled() && a", True),
        ("a", "failure() && a", False),
        ("always()", "a || b", True),
    ],
)
def test_covers_compares_normalised_conditions_and_top_level_or_terms(setup, step, covered):
    assert covers(Step(condition=setup), Step(condition=step)) is covered


FLOOR_SAMPLE = """\
name: floors
on: push
env:
  PYTHON_VERSION: "3.15"
  OLD: "3.14"
jobs:
  old:
    steps:
      - uses: actions/setup-python@abc
        with: { python-version: "3.14" }
  new:
    steps:
      - uses: actions/setup-python@abc # v6
        with:
          python-version: "3.15"
      - uses: actions/setup-python@abc
        with: { python-version-file: .python-version }
      - uses: actions/setup-python@abc
        with: { python-version: "${{ env.PYTHON_VERSION }}" }
      - uses: actions/setup-node@abc
        with: { node-version: 26, package-manager-cache: false }
  old-node:
    steps:
      - name: Node
        uses: actions/setup-node@abc
        with: { node-version: "24" }
  through-env:
    env:
      PYTHON_VERSION: ${{ env.OLD }}
    steps:
      - uses: actions/setup-python@abc
        with: { python-version: "${{ env.PYTHON_VERSION }}" }
      - uses: actions/setup-python@abc
        with: { python-version-file: .old-version }
  matrix:
    strategy:
      matrix:
        python-version: ["3.15", "3.14"]
    steps:
      - uses: actions/setup-python@abc
        with: { python-version: "${{ matrix.python-version }}" }
  unreadable:
    steps:
      - uses: actions/setup-python@abc
      - uses: actions/setup-node@abc
        with: { node-version: "${{ inputs.node }}" }
      - uses: actions/setup-node@abc
        with: { node-version: lts/* }
"""


def test_a_set_up_step_must_ask_for_the_floor_or_newer(tmp_path):
    (tmp_path / ".python-version").write_text("# the line uv and setup-python read\n3.15\n", encoding="utf-8")
    (tmp_path / ".old-version").write_text("3.14\n", encoding="utf-8")
    assert floor_problems("x.yml", workflow_jobs(FLOOR_SAMPLE), tmp_path) == [
        "x.yml > old > step 1 > python: asks for 3.14, below the floor",
        "x.yml > old-node > Node > node: asks for 24, below the floor",
        "x.yml > through-env > step 1 > python: asks for 3.14, below the floor",
        "x.yml > through-env > step 2 > python: asks for 3.14, below the floor",
        "x.yml > matrix > step 1 > python: asks for 3.14, below the floor",
        "x.yml > unreadable > step 1 > python: cannot work out the version it asks for",
        "x.yml > unreadable > step 2 > node: cannot work out the version it asks for",
        "x.yml > unreadable > step 3 > node: 'lts/*' is not a version number this test can compare",
    ]


@pytest.mark.parametrize(
    ("version", "kind", "below"),
    [
        ("26.0.0", "node", True),
        ("26.10.0", "node", True),
        ("26.11.0", "node", False),
        ("26", "node", False),
        ("26.x", "node", False),
        ("v27.0.0", "node", False),
        ("24", "node", True),
        ("3.15", "python", False),
        ("3.15.0", "python", False),
        ("3.14.9", "python", True),
        ("3.14", "python", True),
        ("lts/*", "node", None),
    ],
)
def test_a_line_meets_the_floor_by_its_line_and_an_exact_version_in_full(version, kind, below):
    assert _below_floor(version, kind) is below


UV_SAMPLE = """\
name: uv
on: push
jobs:
  no-version:
    steps:
      - uses: astral-sh/setup-uv@abc
      - name: Test
        run: uv run pytest
  new:
    steps:
      - uses: astral-sh/setup-uv@abc
        with: { python-version: "3.15", enable-cache: false }
      - name: Test
        run: uv run pytest
  old:
    steps:
      - uses: astral-sh/setup-uv@abc
        with: { python-version: "3.14" }
      - name: Test
        run: uv run pytest
"""


def test_setup_uv_sets_python_up_only_with_a_python_version_at_the_floor():
    jobs = workflow_jobs(UV_SAMPLE)
    assert unset_steps("x.yml", jobs, {}) == ["x.yml > no-version > Test > python", "x.yml > old > Test > python"]
    assert floor_problems("x.yml", jobs) == ["x.yml > old > step 1 > python: asks for 3.14, below the floor"]


def test_every_set_up_step_asks_for_the_floor_or_newer():
    assert [problem for file, (_, jobs) in every_file().items() for problem in floor_problems(file, jobs)] == []


def test_a_composite_action_is_checked_on_its_own_steps():
    action = (
        "name: sample\nruns:\n  using: composite\n  steps:\n    - name: Script\n      shell: bash\n"
        "      run: |\n        python3 x.py\n    - uses: actions/setup-python@abc\n"
    )
    assert unset_steps("a/action.yml", action_jobs(action)) == ["a/action.yml > (composite) > Script > python"]
    assert action_jobs("name: js\nruns:\n  using: node24\n  main: index.js\n") == {}


def test_the_reader_sees_every_step_of_every_file():
    """Guard against the indentation reader missing a step, which would let an unset step pass unseen: the number of
    `run:` and `uses:` keys in each file's text equals what the reader found, and every job has steps."""
    for file, (text, jobs) in every_file().items():
        steps = [step for job in jobs.values() for step in job.steps]
        assert jobs or "runs:" in text, file
        assert all(job.steps for job in jobs.values()), file
        assert len([s for s in steps if s.run]) == len(re.findall(r"(?m)^\s*(?:- )?run:", text)), file
        assert len([s for s in steps if s.uses]) == len(re.findall(r"(?m)^\s*(?:- )?uses:", text)), file


def test_every_step_that_runs_node_or_python_comes_after_its_version_is_set_up():
    unset = [entry for file, (_, jobs) in every_file().items() for entry in unset_steps(file, jobs)]
    assert [entry for entry in unset if entry not in RUNNER_DEFAULT_ALLOWED] == []


def test_an_indirect_step_counts_as_running_its_runtime():
    jobs = workflow_jobs(SAMPLE)
    key = "x.yml > good > Install > node"
    assert key in unset_steps("x.yml", jobs, {key: "a script it runs starts node"})
    assert key not in unset_steps("x.yml", jobs, {})


def test_every_indirect_step_still_exists():
    """So a renamed or removed step cannot leave the indirect list pointing at nothing."""
    keys = {
        step_key(file, name, step, i, kind)
        for file, (_, jobs) in every_file().items()
        for name, job in jobs.items()
        for i, step in enumerate(job.steps)
        for kind in COMMAND
    }
    for entry, reason in INDIRECT_RUNTIME.items():
        assert reason.strip(), entry
        assert entry in keys, entry


def test_every_allowed_exception_still_exists():
    """So the list cannot hide a step that has since changed or gone."""
    unset = [entry for file, (_, jobs) in every_file().items() for entry in unset_steps(file, jobs)]
    for entry, reason in RUNNER_DEFAULT_ALLOWED.items():
        assert reason.strip(), entry
        assert entry in unset, entry
