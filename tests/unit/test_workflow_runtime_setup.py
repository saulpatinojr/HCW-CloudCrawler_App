"""Every workflow step that runs Node.js or Python on the runner comes after the job chooses its version (#1707).

A job that runs `node`, `npm`, `npx`, `python`, `python3`, `pip` or `uv` without actions/setup-node or
actions/setup-python gets whatever the runner image ships: on ubuntu-26.04 in November 2026 that was Node.js 24 and
Python 3.14, both below the HCW floors (Node.js 26, Python 3.15; HCW-HybridCloudWorks issue #1707). `uv` counts as
Python, because without setup-python it would pick the runner's own Python. Nothing else would notice, because a job
that names no version has nothing for a version check to read. This is a port of the website's
`scripts/workflow-runtime-setup.test.mjs`.

A command counts when it is in command position on a line of a `run:` step: at the start, after `$(`, `<(`, `(`, `{`,
`|`, `&&`, `||` or `;`, after leading `NAME=value` assignments, or after a word that runs the next one (`env`, `sudo`,
`xargs`, `exec`, `time`, `!`, `if`, `then`, `do` and the like). It does not count inside a quoted string (unless the
string runs a command with `$(` or `<(`), on a comment line, or as an argument (`docker run image python ...`). The
set-up step must come before the first such step. Limits, on purpose: a job that runs in a `container:` uses that
image's runtime and is not checked; a script a step calls (a `.sh` or `.py` file) is not read; a set-up step with its
own `if:` counts as done, so give it the same condition as the steps that need it; and a composite action is checked on
its own steps only, because the job that calls it is in another file. The repository has no YAML library (see
test_workflows.py), so the files are read by indentation; the last tests check that the reader saw every step."""

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

# Where a command may start: the line's start or an opening/joining character, then any `NAME=value` assignments and
# words that run the next word (`env FOO=1 node`, `sudo node`, `if node ...; then`).
START = (
    r"(?:^|[$<]\(\s*|[({|;&]\s*)"
    r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+|(?:env|sudo|xargs|exec|time|nice|command|if|then|else|elif|do|while|until|!)\s+)*"
)
COMMAND = {
    "node": re.compile(START + r"(?:node|npm|npx)(?=\s|$)"),
    "python": re.compile(START + r"(?:python(?:3(?:\.\d+)?)?|pip3?|uvx?)(?=\s|$)"),
}
SETUP = {"node": re.compile(r"^actions/setup-node@"), "python": re.compile(r"^actions/setup-python@")}


@dataclass
class Step:
    name: str | None = None
    uses: str = ""
    run: str = ""


@dataclass
class Job:
    container: bool = False
    steps: list[Step] = field(default_factory=list)


def without_quoted_text(line: str) -> str:
    """The line with the text of its quoted strings taken out, so words in a message (`echo "...; if pip named..."`)
    do not count. A double-quoted string that runs a command (`"$(node x)"`) is kept."""
    line = re.sub(r"'[^']*'", "''", line)
    return re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: m.group(0) if re.search(r"[$<]\(", m.group(0)) else '""', line)


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
    jobs = {}
    for n, head in enumerate(heads):
        stop = heads[n + 1] if n + 1 < len(heads) else end
        job = Job(container=any(re.match(r"^    container:", lines[i]) for i in range(head, stop)))
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


def unset_steps(file: str, jobs: dict[str, Job]) -> list[str]:
    """The steps that run a runtime before (or without) setting it up: "file > job > step > runtime"."""
    found = []
    for name, job in jobs.items():
        if job.container:
            continue
        for kind in COMMAND:
            setup = next((i for i, step in enumerate(job.steps) if SETUP[kind].search(step.uses)), None)
            for i, step in enumerate(job.steps):
                if (setup is None or setup > i) and runs_runtime(step.run, kind):
                    found.append(f"{file} > {name} > {step.name or f'step {i + 1}'} > {kind}")
    return found


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
        'token="$(node scripts/github-app-token.mjs)"',
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
    ],
)
def test_python_and_uv_in_command_position_count(line):
    assert runs_runtime(line, "python")


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        ('echo "run `node scripts/x.mjs` by hand"', "node"),
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


def test_every_allowed_exception_still_exists():
    """So the list cannot hide a step that has since changed or gone."""
    unset = [entry for file, (_, jobs) in every_file().items() for entry in unset_steps(file, jobs)]
    for entry, reason in RUNNER_DEFAULT_ALLOWED.items():
        assert reason.strip(), entry
        assert entry in unset, entry
