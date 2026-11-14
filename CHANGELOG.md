# Changelog

All notable changes to this repository are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) where it versions
anything.

Add an entry under **Unreleased** in the same pull request as the change.
Several open pull requests collide on this section, so when two are open at
once, merge one before rebasing the next.

## [Unreleased]

### Added

- **CI now checks the workflow files and the Dockerfile with the same three linters as the lab edition, and checks that
  every workflow installs the same uv**
  ([HCW-HybridCloudWorks issue #1707](https://github.com/saulpatinojr/HCW-HybridCloudWorks/issues/1707), following
  [HCW-HybridCloudWorks issue #1575](https://github.com/saulpatinojr/HCW-HybridCloudWorks/issues/1575)). A linter is a
  tool that reads a file and reports mistakes without running it. The `lint` job in `ci.yml` (already a required check;
  no job is added or renamed, and no workflow file is added, so the workflow set in `tests/unit/test_workflows.py` is
  unchanged) gains these steps, copied from the lab edition's `ci.yml` with the same versions and digests:
  **actionlint 1.7.12** (workflow mistakes, with shellcheck on their scripts), **zizmor 1.31.1** (workflow security,
  on the workflows and on the composite action in `.github/actions`, which is handed the App key) and
  **hadolint 2.14.0** (`infrastructure/docker/Dockerfile`). Each is downloaded at its pinned version and its
  SHA-256 (a fingerprint of the file) is checked before it runs; the three values were checked again against the
  publishers' own checksum files and PyPI on 2026-11-14. `.github/actionlint.yaml`, the same file as the lab edition's,
  tells actionlint that `ubuntu-26.04` is a GitHub-hosted runner. zizmor reported one low finding, which was already
  there: `rehearse-self-merging-pr.yml` runs this repository's own action with `uses: ./...`, where GitHub now offers a
  safer `uses: $/...` form
  ([GitHub's announcement](https://github.blog/changelog/2026-07-30-reference-same-repository-actions-with-self-repository-syntax/),
  [zizmor's explanation](https://docs.zizmor.sh/audits/#self-repository)). The pinned actionlint does not understand
  `$/` and fails on it, so that one line is ignored in the new `.github/zizmor.yml`, with the reason written there
  (only a `printf` runs between the checkout and that line) and the step to undo it once actionlint accepts `$/`.
  zizmor matches the ignore against the whole step, so moving the step down by a line can keep it ignored; the file
  says to check the line number whenever the workflow changes. zizmor still fails the step on every other finding of
  any severity, as in the lab edition. A new step, **Every workflow uses the uv this workflow uses**, runs a new script,
  `scripts/check_uv_pins.py`. It uses only Python's standard library, because it runs before uv is installed, and it
  is the same file in HCW-CloudAssessor_App. `UV_VERSION` in `ci.yml` is the one uv version. The step names the
  workflows that must install it (`pages.yml`, `publish-core.yml`, `security.yml` and `dependabot-lockfiles.yml`); the
  script fails if one of them is missing or does not install that uv. An install counts only as an argument of a `pip`,
  `pipx`, `uv pip` or `uv tool` install command in a `run:` script, outside a comment, so `echo "uv==…"` or a
  commented-out line does not count; and `uv==${UV_VERSION}` counts only in a file that sets `UV_VERSION` outside a
  comment (a YAML key or a shell assignment). It then reads every `.yml` and `.yaml` file under
  `.github/workflows` and every `action.yml` and `action.yaml` under `.github/actions`, at any depth, line by line (so
  the second install in `publish-core.yml` is checked too), and fails on: uv pinned to anything but `==` and that
  exact version (any operator, including `===`, `~=`, `!=`, `>=` and `uv@…`; any spacing; any extras; and the name in
  any case or spelling pip reads as uv, such as `UV` or `Uv[foo.bar]`); pip, pipx, `uv pip` or `uv tool` installing
  uv with no version; `uses: astral-sh/setup-uv`, or the `ghcr.io/astral-sh/uv` image at another tag; `UV_VERSION`
  given another value in any YAML or shell form; and `${UV_VERSION}`, `$UV_VERSION` or `env.UV_VERSION` in a file that
  never sets it. These are reported wherever they are written, comments included. Other packages are left alone (`pyuv`, `uvicorn`, `uv-dynamic-versioning`), and so is `uv_==…`,
  which pip refuses as a name. What it cannot see: a version worked out while a job runs, or an install written in a
  way these patterns do not describe. `tests/unit/test_check_uv_pins.py` (also the same file in both repositories)
  builds a small made-up repository for each of 50 changes that must fail and 21 that must pass, and runs the script
  on this repository with the file list `ci.yml` gives it. `setup-python` in the `lint` job now also runs after an
  earlier failure, because the zizmor install makes a Python environment with `python3 -m venv` (zizmor comes from
  PyPI) and runs then too. Nothing here reaches the
  lab edition: it already runs these steps, and no engine, tool schema or release asset changed, so its
  `docs/whats-new-upstream.md` needs no entry. What ran is in `VALIDATION.md`. The three linters and then the uv check
  run first in the `lint` job, straight after setting up Python and before uv is installed (from Copilot's review of
  the MigrateOrchestrator_App change): before, they ran after `uv sync` and the repository's own scripts, so code in a
  pull request could have rewritten `.github` on disk before it was read.

- `tests/unit/test_workflow_runtime_setup.py` fails when a workflow or composite-action step runs `node`, `npm`, `npx`,
  `python`, `pip` or `uv` on the runner before its job has run `actions/setup-node` or `actions/setup-python`, so the
  runner image's own, older Node.js or Python cannot come back unnoticed
  ([HCW-HybridCloudWorks issue #1707](https://github.com/saulpatinojr/HCW-HybridCloudWorks/issues/1707)); a deliberate
  exception needs an entry with a reason in its allow-list, which is empty today. A step that starts a runtime through
  a program it runs (the `contract` job's test starts `npx`) is listed in `INDIRECT_RUNTIME` and checked the same way.
  A set-up step with its own `if:` covers only later steps under the same condition (or one of its top-level `||`
  terms), a command in backticks counts like one in `$(...)`, and every set-up step must ask for Python 3.15 or
  Node.js 26 or newer. A step's condition now counts GitHub's unwritten `success()`, a quoted `NAME="a b"` prefix
  counts, setup-uv sets Python up only with a `python-version`, an exact version must meet the full floor (Node.js
  26.11.0), and the two lockfile steps that run uv through a script are listed in `INDIRECT_RUNTIME`.
  A path in front of the interpreter (`/usr/bin/python3`) now counts, as do `python3.15.2`, a wrapper's options
  (`sudo -u nobody`) and a command after a `case` pattern, while a heredoc, a comment or a script quoted across lines
  for a container does not; `&&` and `||` of status functions are followed; and a version with trailing text
  (`26.11.0-rc.1`, `26.11.0.0`) is reported as unreadable.
- `.qlty/qlty.toml` pins qlty's ruff to 0.17.4, the version in `uv.lock`: qlty's own default, 0.14.6, cannot read
  `target-version = "py315"`, so `qlty check` errored on the whole pull request.
- `scripts/check-versions.sh` checks that the base image pin in `infrastructure/docker/versions.env` and every `FROM`
  line of `infrastructure/docker/Dockerfile` agree: each `FROM` must be `PYTHON_IMAGE@PYTHON_IMAGE_DIGEST` (or an
  earlier stage of the same file), the digest must be `sha256:` and 64 hex characters, and the tag must carry
  `PYTHON_VERSION`. It is ported from the Cloud Assessor App's script of the same name and runs in the `lint` job of
  `ci.yml` and in `make lint`. Until now nothing compared the two files, so a digest changed in one place and not the
  other would only have been caught by eye. `tests/unit/test_check_versions.py` runs it against the real files and
  against altered copies (a different digest, a different tag, a version the tag does not carry, a value that is not a
  digest, no `FROM` at all), each of which must fail. The sentences in `versions.env` and `infrastructure/README.md`
  that said nothing in CI compares the two now name the check, and `docs/testing.md`, `docs/troubleshooting.md` and
  `CONTRIBUTING.md` list it.

### Changed

- **Python 3.15.2 is now the minimum.** The owner decided on 2026-11-14 that every Hybrid Cloud Works Python
  repository requires the latest stable release of Python 3.15, which is 3.15.2 (released 2026-10-25). What moved:
  - `requires-python` in both `pyproject.toml` files (the App and the engine `cloud-crawler-core`), from
    `>=3.15.1,<3.16` to `>=3.15.2,<3.16`.
  - `uv.lock` re-locked with `make lock` and uv 0.13.8, the version the workflows install. Only the lock's own Python
    range changed: no package version moved, and `requirements.lock.txt` came out exactly as it was.
  - `README.md`, `CONTRIBUTING.md` and `docs/quick-start.md` now say 3.15.2, and that letting uv download it needs
    uv 0.13.6 or newer (0.13.5 offers only up to 3.15.1).
  - `make setup` now runs `uv python pin --no-project 3.15`. `.python-version` still names the line only, `3.15`, but
    uv refuses to pin that line against the new range (the line also covers 3.15.0 and 3.15.1), so `make setup`
    stopped with "The requested Python version `3.15` is incompatible". `--no-project` skips only that check;
    `uv sync` still picks an interpreter inside `>=3.15.2,<3.16`.
  - **The AddOn.** The engine wheel's `Requires-Python` becomes `>=3.15.2,<3.16` from the next release (the published
    v0.1.1 wheel is unchanged). The AddOn moves its own floor to 3.15.2 in a matching change and already runs 3.15.2,
    so `core-update.yml` adopts that release as usual. The image already ran `python:3.15.2-slim-trixie`, so it does
    not change.
- **The workflows read the uv version as a shell variable** ([HCW-HybridCloudWorks#1707](https://github.com/saulpatinojr/HCW-HybridCloudWorks/issues/1707)). In the three `uv` install steps of `ci.yml` and the one in `dependabot-lockfiles.yml`, `python -m pip install "uv==${{ env.UV_VERSION }}"` becomes `python -m pip install "uv==${UV_VERSION}"`. `UV_VERSION` is set once in the workflow's own `env:` block, so the version installed is the same; the difference is that GitHub no longer pastes the value into the script text before the shell runs it (a `${{ }}` expression is filled in first, which zizmor, the workflow security checker, reports as a possible template injection at its strictest setting). The other steps of the same file already wrote it this way. No job name changes.
- **opentelemetry-api 1.45.2 fixes CVE-2026-126360.** The `pip-audit` check (it looks up every locked Python package in the public list of known security problems) failed on 2026-11-13 because the lock still held `opentelemetry-api` 1.45.1, for which CVE-2026-126360 was published with 1.45.2 as the fix. `uv lock --upgrade-package opentelemetry-api` moves only that package; nothing else in the lock changes, apart from the lock format number uv 0.13.7 writes (3 to 5), and `requirements.lock.txt` is exported again from it. Found during the workflow runtime-check work ([HCW-HybridCloudWorks#1707](https://github.com/saulpatinojr/HCW-HybridCloudWorks/issues/1707)), not tracked by an issue of its own.
- The workflow runtime check is refreshed to round two
  ([HCW-HybridCloudWorks#1707](https://github.com/saulpatinojr/HCW-HybridCloudWorks/issues/1707)).
  `tests/unit/test_workflow_runtime_setup.py` is the test that fails when a workflow step runs Node.js or Python before
  its job has chosen the version, so the runner's own older versions cannot slip back in unnoticed. Its logic and test
  cases are taken unchanged from the canonical Python copy in HCW-NetworkEyes_App
  ([HCW-NetworkEyes_App#395](https://github.com/saulpatinojr/HCW-NetworkEyes_App/pull/395)), which works the same way as
  the website's own check ([HCW-HybridCloudWorks#1719](https://github.com/saulpatinojr/HCW-HybridCloudWorks/pull/1719));
  only the lists of this repository's own steps are its own. It now reads a script the way the shell runs it in more
  places: the script a shell is fed through a heredoc (`bash <<'EOF'`, a block of text handed to a command), the
  commands a heredoc's text runs with `$(...)`, and `$'...'` strings, while the rest of a heredoc's text and a `$` the
  shell passes on as text stay plain text. A step that runs `pipx` must hand pipx the Python a set-up step installed:
  the runner's own (`/usr/bin/python3`, or the Azure CLI's `/opt/az/bin/python3`) and a value the test cannot work out
  (`"$(command -v python3)"`) no longer count, `${{ steps.<id>.outputs.python-path }}` counts only from an earlier
  `actions/setup-python` step that is sure to have run, a shell variable set earlier in the script counts only in the
  same shell, and `sudo` passes the setting on only with `-E` or `--preserve-env`. Composite actions
  (`.github/actions/<name>/action.yml`, a list of steps that workflows reuse) are checked like a job of their own. A
  version file is read only when it is a `.python-version`, `.nvmrc` or `.node-version` file inside the checkout,
  `3.15.x` reads as the 3.15 line, YAML's folded `>` scripts and empty values are read as YAML reads them, and a
  workflow written in a shape the reader cannot follow (a step list on one line) now fails the test instead of being
  skipped. This copy's own check of composite actions, kept from before, is dropped, because the shared copy now reads
  them itself: `.github/actions/self-merging-pr/action.yml` is read with the same rules, and an exception for one of its
  steps would be keyed `.github/actions/self-merging-pr/action.yml > composite > step name > runtime` (it was
  `actions/self-merging-pr/action.yml > (composite) > ...`; no exception used the old key). Nothing new was found here:
  the composite action runs only `gh`, and no workflow runs pipx. The three steps that start a runtime through a program
  (the `contract` job's test, which starts `npx`, and the two lockfile steps that run uv through a script) stay in
  `INDIRECT_RUNTIME`, the list of steps that start a runtime the check cannot see: the check still does not read the
  runtime in their own `run:` text. It also carries the fourth review round's fixes (Copilot on
  [HCW-NetworkEyes_AddOn#109](https://github.com/saulpatinojr/HCW-NetworkEyes_AddOn/pull/109),
  [HCW-MigrateOrchestrator_AddOn#75](https://github.com/saulpatinojr/HCW-MigrateOrchestrator_AddOn/pull/75) and
  [HCW-MigrateOrchestrator_App#118](https://github.com/saulpatinojr/HCW-MigrateOrchestrator_App/pull/118)): a comment
  after a block value in `env:` or `with:` (a value written over several lines after `|`) ends the value instead of
  being read into it; a GitHub expression given to pipx chooses its Python only when it is setup-python's `python-path`
  output, `env.pythonLocation`, or an `env.X` or `matrix.X` whose value does, and `$pythonLocation` counts only after a
  set-up step; a runner path written with `.` or `..` (`/usr/bin/../bin/python3`) is still the runner's; and a set-up
  step under `(a || b) && c` now covers a later step under `a && c`. No workflow changed. The AddOn
  (HCW-CloudCrawler_AddOn) gets the same change in its own pull request, with its own `docs/whats-new-upstream.md`
  entry.
- The workflow runtime check, `tests/unit/test_workflow_runtime_setup.py`, is now the finished copy every HCW
  repository runs ([HCW-HybridCloudWorks issue
  #1707](https://github.com/saulpatinojr/HCW-HybridCloudWorks/issues/1707)). It is the test that fails when a workflow
  step runs Node.js or Python before its job has chosen the version, so the runner's own older versions cannot slip
  back in unnoticed. It now carries the same logic and test cases as the original (the website's
  `scripts/workflow-runtime-setup.test.mjs`), taken from the Python copy in `saulpatinojr/HCW-NetworkEyes_App`;
  only the lists of this repository's own steps are its own.
  What the finished copy reads that this one did not: `yarn` and `pnpm` count as Node.js, and `pytest` and `pipx`
  as Python; a step that runs `pipx` must also say which Python pipx uses (`--python`, or `PIPX_DEFAULT_PYTHON` in
  front of it or in an `env:` block), because pipx otherwise builds its tools on the runner's own Python even after
  `actions/setup-python`; the script given to `bash -c` or `sh -c` is read, while the same words handed to a
  container stay the container's; more words that run the next word are followed (`nohup`, `stdbuf`, `timeout`,
  `env -S`, `command -p`, `--`); and a set-up step's own `if:` covers a later step only when that step's condition
  makes it true, never by matching text that a step can change (`env.*`, `steps.*` of a later step).
  Two empty lists join it: `PIPX_ALLOWED` and `BELOW_FLOOR_ALLOWED`, for a deliberate exception with its reason.
  This repository's copy keeps one addition of its own from before: it also checks the steps of each composite
  action under `.github/actions` (the website's and the add-ons' copies read workflows only), now with the same
  reader as the workflows.
  Nothing new was found here: every step already sets its version up first, and no workflow runs pipx. The three
  steps that start a runtime through a program (the `contract` job's test, which starts `npx`, and the two lockfile
  steps that run uv through a script) stay in `INDIRECT_RUNTIME`; every other script a workflow calls was read on
  2026-11-13 and starts nothing the check cannot see. No workflow changed. The AddOn already runs the identical
  check, so its `docs/whats-new-upstream.md` needs no entry.
- **uv 0.13.7 to 0.13.8 in every workflow** ([HCW-HybridCloudWorks issue
  #1707](https://github.com/saulpatinojr/HCW-HybridCloudWorks/issues/1707)). uv is the tool that installs this
  repository's Python packages and keeps `uv.lock` (the file that records the exact versions installed). 0.13.8 is a
  small bug-fix release ([its release notes](https://github.com/astral-sh/uv/blob/0.13.8/CHANGELOG.md)) and does not
  change how the lock file is written. The pin moved in the same places as last time: `ci.yml` and
  `dependabot-lockfiles.yml` (`UV_VERSION`), `security.yml`, `pages.yml` and both install steps of `publish-core.yml`;
  `tests/unit/test_workflows.py` now expects 0.13.8 in the release workflow (the `--no-create-gitignore` build flag it
  guards is still there in 0.13.8), and the uv wording in `README.md` and `CONTRIBUTING.md` follows. No lockfile
  changed. The engine wheel and its source archive built by 0.13.8 are byte-identical to 0.13.7's; the software bill
  of materials (`cloud-crawler-core.cdx.json`) lists the same five packages, and only its tool version line, its
  random serial number and its timestamp differ (the last two differ on every run anyway). `VALIDATION.md` has the
  details.
- **uv 0.11.32 to 0.13.7 in every workflow** ([HCW-HybridCloudWorks issue
  #1707](https://github.com/saulpatinojr/HCW-HybridCloudWorks/issues/1707)). uv is the tool that installs this
  repository's Python packages and keeps `uv.lock` (the file that records the exact versions installed). The old
  version could download only a beta of Python 3.15; 0.13.0 is the first uv that can fetch a finished 3.15 (3.15.0)
  and 0.13.5 the first to offer the 3.15.1 this repository requires, and 0.13.7 is the version
  `saulpatinojr/HCW-NetworkEyes_App` already uses, so the App repositories now share one uv. The pin moved in `ci.yml`
  and `dependabot-lockfiles.yml` (`UV_VERSION`), `security.yml`, `pages.yml` and both install steps of
  `publish-core.yml`; `tests/unit/test_workflows.py` now expects 0.13.7 in the release workflow (the
  `--no-create-gitignore` build flag it guards was checked again in 0.13.7), and the uv wording in `README.md` and
  `CONTRIBUTING.md` follows. `uv lock --check` passes with uv 0.13.7 and a fresh export leaves `uv.lock` and
  `requirements.lock.txt` exactly as they were, so no lockfile changed. No Dockerfile copies uv (the image installs
  from the exported lock file with pip), so the image does not change. One visible difference: the release's software
  bill of materials (`cloud-crawler-core.cdx.json`, the list of what the engine wheel depends on) made by uv 0.13.7
  lists the same five packages but also gives each one's download addresses and sha256 hashes, so the file grows from
  about 2 KB to about 19 KB. `VALIDATION.md` has the details.
- Python 3.15 and Node.js 26, the HCW runtime floors (the newest Python line and the newest Node.js long-term-support
  line; [HCW-HybridCloudWorks issue #1707](https://github.com/saulpatinojr/HCW-HybridCloudWorks/issues/1707)). Before,
  this repository ran Python 3.14 and its contract test ran on Node.js 22, while the website and the AddOns were
  already on 3.15.2.
  - **The image.** Its base moves from `python:3.14.10-slim-trixie` to `python:3.15.2-slim-trixie` (CPython 3.15.2 on
    Debian 13), pinned by its index digest `sha256:65a65fc7b30b…` in `infrastructure/docker/versions.env` and in both
    `FROM` lines of `infrastructure/docker/Dockerfile`. It is the same pin as the website's lab image and the Cloud
    Crawler AddOn, and on 2026-11-12 Docker Hub showed `python:3.15-slim-trixie` on the same digest and no 3.15.3. The
    Dockerfile's `python3.14` folder names become `python3.15`.
  - **Python everywhere else.** `.python-version` now names the 3.15 line (`3.15`, as the AddOn does) instead of
    3.14.6, `make setup` pins the same, `requires-python` in both `pyproject.toml` files is `>=3.15.1,<3.16` (the
    AddOns' range), ruff checks against `py315`, and every workflow's `setup-python` asks for `3.15`. `uv.lock` and its
    export `requirements.lock.txt` were made again with uv 0.11.32 (the version the workflows install): no package
    version changed; only the Python 3.14 wheels and one 3.14-only marker dropped out. Every locked package has a
    wheel for 3.15, so nothing is compiled from source. uv 0.11.32 cannot download a finished Python 3.15 by itself, so
    `CONTRIBUTING.md` now says to install 3.15 first; in CI, `setup-python` does that.
  - **Node.js.** The `contract` job in `ci.yml` installs Node.js 26 instead of 22. ADR 0001 said Node.js 22 was needed
    for `npx @azure/mcp@3.0.0`, but the package accepts Node.js 22 or later (its npm `engines` field), so the ADR gains
    a dated "Update of 2026-11-12" rather than a rewritten line, and the README, `CONTRIBUTING.md`, the docs and the
    "npx is not on PATH" messages say Node.js 26.
  - **The AddOn.** The engine wheel's `Requires-Python` becomes `>=3.15.1,<3.16` from the next release (the published
    v0.1.1 wheel is unchanged). The AddOn already requires 3.15.1 or later and runs 3.15.2, so it needs no change.
  - Every job that runs Python or Node.js already chooses its version with `setup-python` or `setup-node`; none relies
    on the runner's own interpreter, so no step was added. Checks run: `VALIDATION.md`, "Ran for the move to Python
    3.15 and Node.js 26".
- The appliance image's base moves from `python:3.14.8-slim-trixie` to `python:3.14.10-slim-trixie` (CPython 3.14.10 on
  Debian 13), pinned by its index digest `sha256:af8a5aa14780…` in `infrastructure/docker/versions.env` and in both
  `FROM` lines of `infrastructure/docker/Dockerfile` together. 3.14.10 is the newest Python 3.14 build on Docker Hub
  (read on 2026-11-07; `python:3.14-slim-trixie` points at the same digest and no 3.14.11 exists), and it is the same
  pin as the Cloud Assessor App. The final stage keeps its `apt-get upgrade` step for Debian security fixes published
  after the base. `.python-version` and `make setup` stay on 3.14.6, the local and CI interpreter (the newest 3.14
  build uv 0.11.32 can download) and the floor of `requires-python`; the image's 3.14.10 is inside the same range.
  The image was not built or scanned in this change; `image-scan.yml` scans it on the pull request (`VALIDATION.md`).
- `dependabot-lockfiles.yml` now says why the HCW Main Admin App's token could not be made when that step fails (issue
  #70). Before, the only message named missing secrets, so a 401 from a wrong key was first read as "not set". The new
  step runs only when the token step fails, after the check that both secrets are present, and names the usual causes:
  a private key that is not that App's, a Client ID that is not that App's, or the App not installed on this
  repository. `tests/unit/test_workflows.py` pins it. Repository process only; nothing in the engine, the image or the
  API changes.

- CodeRabbit, the review bot, is removed until further notice (the owner's instruction of 2026-11-06): its settings file
  `.coderabbit.yaml` is deleted and the README no longer lists it among the repository's configuration. Earlier
  `VALIDATION.md` sections, the decision record and the test comments that credit a CodeRabbit finding record what was
  true then and stay. Repository process only; nothing in the engine, the image or the API changes. The `Protect main`
  ruleset still requires one approving review, as `.github/workflows/repository-admin.yml` sets it; lowering it there
  and in the live ruleset is the owner's step.

### Security

- The image scan's accepted-risk file (`.trivyignore.yaml`) accepts CVE-2026-119373, CVE-2026-119374 and
  CVE-2026-119379 in `libsqlite3-0` 3.46.1-7+deb13u2 until 2026-12-13, the owner's decision on #80. Each needs a
  program that feeds SQLite crafted full-text-search data, an attacker's database file or an attacker's changeset;
  nothing in the appliance uses SQLite (importing every appliance and engine module, 34, loads neither Python's
  `sqlite3` module nor the C library; checked 2026-11-13). Debian has marked them minor and will not fix them in
  Debian 13. The weekly scan had warned about the three since 2026-11-09.

## [0.1.1] - 2026-11-04

### Security

- **The appliance refuses to start without sign-in on a non-loopback address** (ticket #8, owner decision of 2026-10-26,
  [ADR 0004](docs/adr/0004-entra-token-validation-on-api-and-mcp.md) amendment). With `CC_AUTH_MODE=off` and
  `CC_BIND_HOST` anything but a loopback address, the process now exits 3 and names the way out, unless
  `CC_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true` is set on purpose (lab only; it is refused with sign-in on, and it still
  writes the one `warning` line). The default is unchanged: sign-in off on `127.0.0.1` starts as before. **Behaviour
  change:** the container image binds `0.0.0.0` and does not set the opt-out, so `docker run` with no settings now exits
  3. Run it with sign-in on (`CC_AUTH_MODE=entra`, `CC_ENTRA_TENANT_ID`, `CC_ENTRA_AUDIENCE`) or, in a lab only, add
  `-e CC_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true`. The `ci.yml` image job now proves the refusal, the opt-out start and
  the sign-in start.
- **Optional app-role check** (`CC_AUTH_REQUIRED_ROLES`, comma or space separated app role values, empty by default so
  nothing changes). With sign-in on and roles listed, a valid token whose `roles` claim holds none of them gets `403`
  with a generic body that names no role. Person-only tools still need a delegated token with the scope
  `access_as_user`, exactly as before; the role is a separate gate. Refused when sign-in is off.
- **The engine's secret-shape pattern is no longer quadratic on a repeated `eyJ`, and a token glued to the text in front
  of it is redacted** (ticket [#53](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/53)).
  `redact_payload` runs `_SECRET_SHAPED` (`packages/cloud-crawler-core/src/cloud_crawler_core/redaction.py`) over every
  string it ingests, and its JSON web token alternative took time proportional to the square of the text on a long run
  of `eyJ` with no dot: 65,535 characters (`"eyJ" * 21845`) held the process for about a second, and about 80 such
  strings fit in a 5 MB upload. [Pull request 59](https://github.com/saulpatinojr/HCW-CloudCrawler_App/pull/59) made it
  linear, but its version left a regression. It is on `main` and in no release (the latest tag, `v0.1.0`, does not
  contain it). A token glued directly to a preceding letter, digit, `_` or `-` (`Bearer%20<token>`, `%3D<token>`, an
  escaped `\n<token>`, `x-<token>`) kept its header readable, and a truncated two-part token, a token with an opaque
  payload and an unsigned token (`header.payload.`) were **not redacted at all**. The pattern from before pull request 59
  redacted all of those. This entry replaces the earlier one and fixes the regression.
  The pattern now starts at the start of a run of token characters, skips the part of the run in front of its first
  `eyJ`, and then matches what the old pattern matched from that `eyJ`. The key and header alternatives (`AccountKey=`,
  `SharedAccessKey=`, `sig=`, the private key header) also take a token that follows them in the same run, because their
  values can stop in the middle of a run. **What this is meant to do:** every JSON web token shape the old pattern
  redacted is redacted, glued or not, including behind a key value or a private key header, and the token characters of
  the same run in front of the token are redacted with it (the `20` of `Bearer%20<token>`). **What the tests check:**
  that, on enumerated layouts and on a seeded fuzz of 300,000 texts over the whole pattern, with a copy of the old pattern
  as the yardstick. They are samples, not a proof. **Not covered:** (1) a match stops at the end of the second segment,
  so the signature of a normal three-part token stays readable, as it always did; (2) a key value that runs straight into
  a token swallows the token's first segment, also as before; (3) when two secrets touch with no separator the match
  boundaries can differ from the old pattern. The case seen is a token whose second segment runs into a keyword
  (`<token>.<segment>AccountKey=<value>`), where the key's value stays readable; the old pattern did the same unless a
  `ghp_` match came first. The fuzz shows it in 27 of 300,000 random glued texts, and the tests set a ceiling on that
  count. The page "Known limitations" describes all three.
  Tests: the hostile-set check now covers 42 text families at two sizes (the 30 from before and 12 new ones that chain
  key values and key headers with long runs of `eyJ`), the old quadratic pattern is kept to prove the timing check would
  have caught it (and a key tail that is not optional, to prove the new families are guarded), and a new test file
  compares the pattern with the whole old pattern. These tests fail on the version from pull request 59 and on a fix
  without the key tails. The engine public surface does not change; the fix reaches the AddOn at the next engine release
  (ADR 0002), after which its `MAX_TOKEN_STARTS` guard in `src/cloud_crawler_lab/inputs.py` can be removed.

### Added

- A short sandbox runbook in the README, "Checking sign-in against a real tenant": Azure CLI and PowerShell steps that
  create the Entra app registration with an app role (`CloudCrawler.Access`) and a delegated scope (`access_as_user`,
  deliberately a different value), start the appliance with sign-in on, make seven calls with the expected status codes,
  and clean up. A test fails if the role and the scope values ever match. It has since been run against a real tenant
  (see "Changed" below, and `VALIDATION.md`). The engine package is unchanged, so the AddOn needs no entry in its `docs/whats-new-upstream.md`.
- **The remaining guide pages on the documentation site** (ticket #11): Quick start, Installation, Configuration,
  Deployment, Operations, Testing and Troubleshooting, so the site now has the whole standard page list. Each is a
  numbered procedure for a junior administrator: one action per step, what you should see after it, PowerShell 7 and Git
  Bash commands where they differ, and a link to the official documentation for every outside tool. The commands were run
  before they were written down (`VALIDATION.md` lists which). Deployment and Operations say plainly what is not supported
  yet, and describe the sign-in hardening from the entry above as it now behaves (the start-up refusal, its lab opt-out and
  the optional role check). `pages.yml` now also runs when a file in `docs/*.md` changes; before, a change to a guide page
  alone did not rebuild the site. Documentation and tests only: the engine, the tool schemas and the image are unchanged
  by this entry, so there is nothing for the AddOn's `docs/whats-new-upstream.md`.
- **The engine reads Terraform state and plan evidence** (ticket
  [#54](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/54),
  [ADR 0005](docs/adr/0005-terraform-evidence-is-read-through-a-provider-type-table.md)). The evidence kinds `tf-state`
  (a Terraform state file, version 4) and `tf-plan` (the JSON of `terraform show -json`, format 1.x) were accepted since
  0.1.0 but only stored unread, so every claim about a Terraform resource was `unknown`. They are now normalised into the
  same `NormalizedResource` rows the Resource Graph export gives, through a table of 31 azurerm resource types (and a 32nd,
  the node pool, which joins its cluster) that covers every Azure type a wave-one detector reads (`normalize/terraform.py`, `normalize/terraform_types.py`). Plain words: a
  Terraform state or plan of the sample estate now gives the same verdicts as the Resource Graph export of that estate for
  every claim whose properties Terraform carries: of the 39 judgements in the wave-one acceptance test, 35 are identical
  and the four private endpoint claims, which Terraform keeps in a separate resource, are `unknown` and name the missing
  property. A plan can be judged before anything is built.
  - **Nothing is guessed.** A property the document does not carry, carries as null, or marks sensitive is left out, so
    the detector answers `unknown` and names it. For the three fields that mean "none" when a Resource Graph export omits
    them (`identity`, `tags`, `zones`), a row now lists what its evidence cannot say in the new optional field
    `NormalizedResource.notCarried`, and the `managed-identity`, `tag-required` and `zone-redundancy` readers answer
    `unknown` for them. A Resource Graph export is read exactly as before (`notCarried` is an empty list). A plan
    also says what it does not know: real Terraform leaves a map entry that is only known after apply out of `after` and
    records it in `after_unknown` only, so a map of tags can look complete when it is not. Anything unknown at or under
    `tags` or a zone attribute now makes that field not carried (for `identity`, the block, an element or its type; a new
    resource's `principal_id` and `tenant_id` are always unknown and do not matter), so the tag claims `exists`, `neq` and
    `absent` answer `unknown` instead of a false answer. When a plan has no `resource_changes` and is read from
    `planned_values`, which marks nothing as unknown, tags, identity and zones are always not carried. A claim's tag
    selector and a decision scope's tag selector cannot be applied to a row whose tags are not carried; the claim answers
    `unknown` for it (it used to be not applicable, or silently out of scope). A zone that is a blank string (empty or
    only whitespace), on a virtual machine's `zone` or in a `zones` list, is neither "no zone" nor a zone with a blank
    name: it is not carried, so the zone claims answer `unknown`.
  - **A plan never wins and never closes** (behaviour change in the drift engine and the ledger, for every kind). A
    Terraform plan describes what Terraform would build, not what exists. A plan row no longer replaces a row of the same
    resource from a Resource Graph export, an Azure MCP result or a state, whichever record is later; a verdict that rests
    on plans alone, or one that cites a record the ledger does not hold (a finding that cites nothing keeps the old
    behaviour), no longer closes an open contradiction as `fixed`; a plan still evaluates and can open a contradiction. An observed row that cannot be placed in a decision's tag
    scope (its tags are not carried) is not stood in for by a plan row of the same resource: the answer is `unknown`, unless another observed row of the
    resource is in scope and decides it.
    Before, an export that showed a database not zone redundant followed by a plan that would make it so flipped the
    verdict to supported and closed the contradiction. A finding about a resource now cites the one record its row came
    from (it used to cite every record with a row in scope). A state still behaves as before, and
    `docs/known-limitations.md` says that a state is what Terraform last applied, not what Azure holds.
  - **Secrets stay out.** Values Terraform marks sensitive (`sensitive_attributes`, `after_sensitive`) are withheld before
    any value is read, only the values the table names are copied, and the stored payload is the rows plus a content-free
    summary (`{"resources": [...], "terraform": {...}}`), not the document. **Behaviour change:** `evidence_get` for these
    two kinds used to return the redacted document; it returns the rows. A document that is not a version 4 state or a
    1.x plan used to be stored unread; it is now refused with `invalid_request`. A record that an older engine stored
    that way (possible only in a ledger that outlived an upgrade) is read as holding no rows, where it would otherwise
    have ended a drift evaluation with a validation error.
  - **Bounded.** A document is refused above 100 levels of nesting or 1,000,000 values (checked before hashing and
    redaction, which recurse) with `too_large`, and above `max_rows` rows and folded node pools together with
    `too_many_rows` (a node pool is not a row; before, 160,000 of them with 5,000 clusters took 10 seconds of processor
    time). `CC_MAX_ROWS` counts mapped resource rows and folded node pools together, not every resource in the document
    (`docs/configuration.md` says so). A number that is not finite, an integer of more than 4,300 digits or text with a lone surrogate is refused with
    `invalid_request` instead of a plain error. The normaliser uses no regular expression. The summary also counts the
    instances that carry no sensitivity markers at all (`markersAbsent`), and a saved `terraform show -json` is now
    ignored by `.gitignore` (`*.tfplan.json`, `*.tfstate.json`).
  - **A resource a plan creates** has no Azure id yet: its row is keyed `terraform:<address>`, correlated as a
    `terraform-address`, and takes the subscription the caller declares in the evidence subject.
  - New fictional fixtures (`samples/terraform/`), three goldens and a table snapshot, 369 new tests, and the
    known limits in `docs/known-limitations.md` (private endpoints, data sources, other providers, not yet run against a
    state written by the azurerm provider itself). The tool description of `evidence_ingest` now names the two kinds.
    Engine change: it reaches the AddOn at the next engine release (ADR 0002), where its `docs/whats-new-upstream.md`
    gets its entry; no version is changed here.

### Changed

- **Documents now record the real-tenant sign-in run of 2026-10-26** (ticket #8) instead of saying it "has not been run yet".
  The README runbook "Checking sign-in against a real tenant" was run once in the owner's demo Microsoft Entra tenant
  ([the result](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/8#issuecomment-6409098598)): all seven calls
  answered as written, the person check, the start-up refusal and the role gate worked, and a real version 2.0 token
  carried the expected `iss`, `aud`, `scp` and `roles` values. `VALIDATION.md` has a new dated "Ran" entry and a rewritten
  "Did not run" row; the README, ADR 0004 (a dated update, no decision changed) and the Deployment, Operations,
  Configuration, Known limitations, Security and Testing pages say the same. Still not verified: HTTPS ingress behind a
  public host name, a token from an application permission, an unassigned user with "Assignment required?" on, an
  expired or other-tenant token, signing-key rotation, the `api://<app id>` audience form (and the version 1.0 `iss`
  form) and the `idtyp` claim; only the demo tenant was used. Documentation only: the engine, the tool schemas, the
  image and the code are unchanged, so there is nothing for the AddOn's `docs/whats-new-upstream.md`.
- **The engine and the appliance now accept Python 3.15** (website issue
  [saulpatinojr/HCW-HybridCloudWorks#1386](https://github.com/saulpatinojr/HCW-HybridCloudWorks/issues/1386)). Both
  `pyproject.toml` files said `requires-python = ">=3.14.6,<3.15"`, so the published wheel
  `cloud_crawler_core-0.1.0-py3-none-any.whl` carries `Requires-Python: <3.15,>=3.14.6` and pip refuses to install it
  on Python 3.15 (`Package 'cloud-crawler-core' requires a different Python: 3.15.2 not in '<3.15,>=3.14.6'`). The
  AddOn (`saulpatinojr/HCW-CloudCrawler_AddOn`) is moving to the website's Python 3.15.2 base image and installs that
  wheel with `pip install --require-hashes --no-deps`, which cannot override the range. The ceiling is widened, not
  moved: the range is now `>=3.14.6,<3.16` in both files and in `uv.lock`, the lower bound, the pinned 3.14.6
  interpreter (`.python-version`), the CI runners and the appliance image (`python:3.14.8-slim-trixie`) are unchanged,
  and the test suite was run on 3.14 and on 3.15.2 (see the pull request). This reaches the AddOn only through the
  next release: the version is `0.1.1` in all six places so that the tag `v0.1.1` can publish a wheel whose
  `Requires-Python` admits 3.15 (the `v0.1.0` wheel cannot be changed).
- Dependencies: `pydantic` 2.14.1 → 2.14.2 (the exact pin in `pyproject.toml`) with `pydantic-core` 2.50.1 → 2.50.2, and
  `sse-starlette` 3.5.0 → 3.6.0 (through the `mcp` SDK), in `uv.lock` and `requirements.lock.txt`. This replaces the
  open Dependabot pull requests #62 and #65, which both failed `lint`: #62 rewrote the export in a shape `uv export`
  does not produce, and #65 moved `sse-starlette` in the export alone and left `uv.lock` at 3.5.0. The engine package's
  `pydantic>=2.14,<3` range is unchanged, so nothing reaches the lab edition.
- **Dependabot Python pull requests no longer need a hand-run `make lock`**
  ([ADR 0006](docs/adr/0006-dependabot-pull-requests-regenerate-the-lockfile-export.md)). `.github/dependabot.yml`
  excludes `requirements.lock.txt` from the `uv` entry (`exclude-paths`), so Dependabot edits `pyproject.toml` and
  `uv.lock` only. The new `.github/workflows/dependabot-lockfiles.yml` regenerates the export on Dependabot's own pull
  requests and pushes it with a short-lived, contents-only token of the HCW Main Admin GitHub App (the one the add-ons'
  `core-update.yml` uses; ADR 0006 was amended on 2026-11-04 to reuse it instead of a new App), so the required checks run
  on that commit as on any push (a push made with `GITHUB_TOKEN` would start none, and checks from a
  `workflow_dispatch` run never count as a pull request's required checks). **Owner step:** install HCW Main Admin on this
  repository and add the Dependabot secrets `HCW_MAIN_ADMIN_CLIENT_ID` and `HCW_MAIN_ADMIN_PRIVATE_KEY` (ADR 0006,
  Validation; issue #70); until then the
  workflow stops with an error naming them. `scripts/export-lockfiles.sh` is now the one place the export flags live:
  `make lock` and `scripts/check-lockfiles.sh` call it too. `tests/unit/test_workflows.py` pins what the workflow may do.

## [0.1.0] - 2026-10-25

The first release of the engine `cloud-crawler-core` 0.1.0 and the App edition 0.1.0, first merged in
[saulpatinojr/HCW-CloudCrawler_App#2](https://github.com/saulpatinojr/HCW-CloudCrawler_App/pull/2). The release
carries the engine wheel the AddOn adopts (ADR 0002), the sdist and a CycloneDX SBOM, and provenance and SBOM
attestations for the wheel and the sdist.

In short: the engine (`cloud_crawler_core-0.1.0-py3-none-any.whl`, which depends on pydantic only); the appliance with its
MCP server and `/api/health`; optional Microsoft Entra sign-in (off by default, so use it on a trusted lab network only until
it is turned on, ADR 0004); a pipeline that checks the tag against every package version before it builds anything. Check
where a file came from with `gh attestation verify <file> --repo saulpatinojr/HCW-CloudCrawler_App`.

### Security

- Microsoft Entra sign-in for `/api` and `/mcp` (ticket #8, [ADR 0004](docs/adr/0004-entra-token-validation-on-api-and-mcp.md)). With `CC_AUTH_MODE=entra` every route except `GET /api/health` needs a valid Entra access token: RS256 signature against the tenant's signing keys (JWKS, fetched over HTTPS with a timeout and a short cache), `iss` (v2.0 and v1.0 forms), `aud`, `exp` and `nbf` with a declared clock skew, and `tid`. A failure is `401` with `WWW-Authenticate: Bearer` and the usual error shape; unreachable signing keys are `503`. The token and its claims are never logged. The human-only tools (`adr_accept`, `review_decide`, `collection_run_azure`) take the actor from the token's `oid`, need a person's delegated token (scope `access_as_user`, not an app-only token), and refuse a typed `actorId` that differs; `adr_create` records the token as author. New settings: `CC_AUTH_MODE`, `CC_ENTRA_TENANT_ID`, `CC_ENTRA_AUDIENCE`, `CC_ENTRA_HUMAN_SCOPE`, `CC_ENTRA_CLOCK_SKEW_SECONDS`, `CC_ENTRA_JWKS_CACHE_SECONDS`, `CC_BIND_HOST` (all in `.env.example`). The default is still `off`: a lab-only warning stays in the README. Entra settings with sign-in off, or `entra` without a tenant or audience, stop the start-up. Not tested against a real tenant (`VALIDATION.md`). The engine package is unchanged; the tool schemas make `actorId` optional, which the AddOn's `docs/whats-new-upstream.md` should record.
- The server binds `127.0.0.1` unless `CC_BIND_HOST` is set; the container image sets `CC_BIND_HOST=0.0.0.0`, so the image listens as before. `/api/health` reports `auth`.

### Added

- **First implementation slice of Cloud Crawler, App edition** (website
  proposal *Azure Architecture MCP Appliance on Azure MCP Server 3.0*,
  section 28).
  - `packages/cloud-crawler-core` 0.1.0: the evidence, provenance,
    collection-run, decision, alternative, claim, cost-estimate, drift-finding,
    contradiction, review-proposal and approval models; canonical hashing;
    payload redaction and the content-free log guard; the Azure Resource Graph
    export normaliser; the detector registry with `zone-redundancy` (SQL
    databases, storage accounts, App Service plans, PostgreSQL flexible
    servers, Cosmos DB accounts, AKS clusters, virtual machine scale sets and
    public IP addresses; a single virtual machine row answers `unknown`
    because redundancy is a property of the instance set); the drift engine
    (severity-weighted score, coverage, one proposal per contradicted claim);
    the in-memory ledger; the report bundle with `NOT-AN-AUDIT.md`.
  - The remaining wave-one detectors (proposal section 22): the boolean
    `public-access-disabled` (`publicNetworkAccess`, the PostgreSQL `network`
    block and the AKS private API server; `SecuredByPerimeter` answers
    unknown), `private-endpoint-present` (approved connections only; a
    virtual-network-injected PostgreSQL server answers unknown) and
    `managed-identity` (`identity.type`, optional `identityType` parameter),
    and the valued `tag-required` (`tag` parameter), `sku-allowed` (`field`
    parameter) and `region-allowed`. Valued detectors compare the reading with
    the claim's `eq`, `neq`, `in`, `exists`, `absent`, `gte` or `lte`
    expectation, case-insensitively and ignoring spaces for strings; a reader
    registered under `*` applies to every resource type. Tag names in
    selectors and decision scopes match case-insensitively, as Azure does.
  - The "production platform baseline" sample decision and acceptance
    scenario over all six detectors, with its golden verdicts; the sample
    estate gains a SQL server and a web app.
  - The tool catalogue of proposal section 16 minus the Full-only tools, with
    caller classes in `meta.caller`: `adr_get`, `adr_list`, `evidence_list`
    (no payloads), `evidence_get`, `drift_list`, `contradiction_list`,
    `review_list` and `review_get` for the model; `adr_accept` and
    `review_decide` for a person, taking an object id that is stored only as
    a hash, the approval carrying the hash of the evidence it rested on.
    `adr_create` now creates `draft` or `proposed` decisions only (the input
    schema says so), so acceptance is always a person's act. Tool refusals
    are `ToolError`s whose text starts with a content-free code. The ledger
    gains decision, evidence and proposal listing and update.
  - The Azure MCP host (`mcp_host/`): the pinned contract (version 3.0.0,
    seven namespaces, a read-only tool allow-list the contract test checks
    against the snapshot), the stdio host (the development model: the server
    as a child process, `AZURE_*` variables not passed through except
    `AZURE_TOKEN_CREDENTIALS`), the recorded host that replays
    `samples/azure-mcp`, the result-to-evidence mapping and the standard
    collection sequence; `CC_AZMCP_MODE` (`off`, `stdio`, `recorded`) and
    `CC_AZMCP_RECORDINGS`; `/api/health` `azureConnectivity` names the mode.
  - The engine normalises Azure MCP results by tool (`subscription_list`,
    `group_list`, `advisor_recommendation_list`, `policy_assignment_list`)
    into typed observation rows, and the `EvidenceDetector` shape reads
    them: `advisor-findings`, `retirement-exposure` (the drift engine opens
    a retirement-kind proposal with the date, the Advisor remediation and
    migration considerations) and `policy-assignment-present`.
  - Tools `review_propose` (model) and, only when a host is configured, the
    Full-only `collection_run_azure` (human, the one tool with
    `meta.callsAzure: true`). The "production platform observations" sample
    decision and acceptance scenario.
  - The release pipeline (ADR 0002): one workflow, `publish-core.yml`, started by a tag of the exact form
    `vMAJOR.MINOR.PATCH`, checks the tag against the package versions and the changelog, builds the engine wheel and
    sdist, verifies the wheel with `scripts/verify-core-wheel.py` (the engine present, no cloud SDK, no HTTP client, no
    Azure endpoint, pydantic the only requirement), attests provenance and the SBOM, creates the GitHub Release as a
    draft with the three files, checks them and only then makes it public. That wheel is what the AddOn's
    `core-update.yml` pins.
  - `src/cloud_crawler_appliance` 0.1.0: the edition guard that refuses
    secret-bearing credential variables, `CC_`-prefixed settings, the
    content-free log writer, an MCP server (streamable HTTP, stateless,
    `/mcp`) with `adr_create`, `evidence_ingest` and `drift_evaluate`, and a
    flat `/api/health`.
  - Tests: unit, security (startup refusal, no secrets or real identifiers),
    the zone-redundancy acceptance scenario in-process and over HTTP with a
    golden verdict file, and the Azure MCP Server 3.0.0 contract test with
    its committed `tools/list` snapshot (ADR 0001).
  - The hardened Dockerfile, hash-pinned runtime lock, SHA-pinned `ci.yml`
    and `security.yml`, Dependabot for the uv workspace, `CLAUDE.md`,
    ADRs 0001 to 0003, `VALIDATION.md`, fictional samples and the README.
- Repository created from the template; initialised for the Python stack;
  MIT license; security policy filled in.

- **Release version guard (ticket #7).** `scripts/check-release-version.py` fails when the engine's `pyproject.toml`, the appliance's `pyproject.toml`, the two `__version__` constants and the two `uv.lock` entries do not all name the same plain `X.Y.Z`. It runs in the `lint` job of `ci.yml` on every pull request and in `make lint`, so a version bump that misses a place is caught before anyone tags. For a `v*` tag, and in the dry run (`--rehearse`, which takes the tag to be `v` plus the version), `publish-core.yml` also requires that the tag is `v` plus that version, that `CHANGELOG.md` has exactly one section for it with a date that exists and is not in the future and with real entries (HTML comments and link reference definitions are not entries), that nothing is left under Unreleased (any letter case, with or without brackets), that the tagged commit is on `main`, and that `dist/` holds exactly the wheel and the sdist for that version with the same version inside the wheel. A date more than a week old is only a warning (the release page will show it). A `v*` tag can never be moved or deleted (ruleset "Protect release tags"), so these checks stop a wrong tag from producing a release instead of trying to undo it. 68 tests in `tests/unit/test_release_guard.py`.
- **Dry run and pre-tag check (ticket #7, ticket #16).** `publish-core.yml` can be started by hand (Run workflow) on `main`, and only on `main`: no tag, no release, nothing published. It takes the tag to be `v` plus the package version and runs the same changelog, ancestry and build checks a real tag runs, builds, verifies, writes the SBOM, keeps the three files as a workflow artifact and prints their sha256 and the release notes. Attestations go into the permanent public signing log, so they are created only when "attest" is ticked; a dry run with "attest" ticked, green in `build` and `attest` on the commit that will be tagged, is required before any tag. `scripts/pre-tag-check.py` checks this before the owner tags: the commit must be the tip of `origin/main` (or identical to it in `.github` and `scripts`) and such a dry run must exist for exactly that commit, because a tag on an older commit runs that commit's older workflow. The dry run cannot reproduce an older commit's workflow, nor the tag event itself (whether GitHub starts the workflow for the tag, and the token's behaviour in the release job). 26 tests in `tests/unit/test_pre_tag_check.py`.
- `tests/unit/test_workflows.py` (49 tests) pins the eight workflow files: SHA-pinned actions with a version comment, `ubuntu-26.04`, top-level `contents: read`, no `--clobber`, the tag filter (only `vMAJOR.MINOR.PATCH`), nothing published without a `v*` tag, the write and signing permissions only in the jobs that use them, a time limit on every release job, the guard wired in, and the coverage gate named in `ci.yml` matching `pyproject.toml`. `tests/unit/test_release_publish.py` (39 tests) runs the draft, check and publish steps and the attestation commands against a fake of `gh`.
- **Self-merging pull request, ready for the workflows that will need it.** The composite action `.github/actions/self-merging-pr` (the same file is in every HCW application repository) turns the files a job changed into one pull request on a fixed branch, opened with a short-lived GitHub App token scoped to this repository (Contents and Pull requests write), because `main` is protected by a ruleset that requires a pull request and a pull request opened with `GITHUB_TOKEN` neither is allowed here nor starts the required checks. It can turn on squash auto-merge and wait for the merge. `rehearse-self-merging-pr.yml` (Run workflow) rehearses it against a harmless file: by default it opens the pull request, turns on auto-merge, confirms the required checks start, and closes the pull request again; with `merge` ticked it really merges `.github/rehearsal.txt` once as the end-to-end proof. The credential is the repository-admin App (HCW Portfolio Admin) held by the `admin-ops` environment, an interim choice; `dependabot.yml` now also reads `.github/actions/*` so the action's pins stay current.

- `.github/workflows/repository-admin.yml` (pull request #19): a manual, owner-approved workflow for repository chores. Its tasks are `show-plan`,
  `protect-main`, `protect-release-tags` and `delete-merged-branches`; it runs in the `admin-ops` environment, does nothing unless `apply` is ticked, and uses a
  short-lived GitHub App token limited to this repository. No product code changed. The two rulesets it applied (main requires a pull request and the checks
  `lint`, `test`, `contract`, `pip-audit`, `secret-scan` and `image`; `v*` tags cannot be moved or deleted) are described in the README.
- README: a section "Is there a user interface?" (no: this edition is headless by design, the screens live in the website and the AddOn's pane) and a section on
  branch and tag protection. `docs/adr/README.md` gains an index of the three decisions.
- `docs/whats-new-upstream.md` in the AddOn repository (`HCW-CloudCrawler_AddOn`) records what changes here reach the AddOn; `CLAUDE.md` says to keep it current.

- `tests/security/test_no_secrets.py`: the GUID-scan test now also checks that `.pyc` and `.pyo` files outside a
  `__pycache__` folder are skipped, so the file-suffix filter is covered on its own.

- `CLAUDE.md`: owner-communication rule to give the exact text for every form field, always with a description.

- `CLAUDE.md`: a communication-style section (plain language, junior-administrator audience, step-by-step
  instructions, links).
- **A weekly scan of the container image, and a written record of the risks accepted** (ticket #15). The new workflow
  `image-scan.yml` builds the appliance image every Monday (05:37 UTC), on **Run workflow**, and on a pull request that
  changes `infrastructure/docker/`, `requirements.lock.txt` or the scan files. It runs `scripts/scan-image.sh`, which scans
  the image with Trivy 0.76.1 (pinned by digest, in a read-only container with no capabilities and no Docker socket) and
  **fails on a HIGH or CRITICAL vulnerability that has a fix available**. Vulnerabilities with no fix yet are listed in the
  new accepted-risk file `.trivyignore.yaml`; every entry has an id, a reason, an owner and an expiry date, and
  `tests/unit/test_image_scan.py` fails when one is missing or past its date. The first scan (2026-10-25) found 164
  findings in the Debian base image, none with a fix and none CRITICAL; the 44 HIGH ones are 8 distinct vulnerabilities,
  each recorded with a reason (proposed; the owner accepts them by merging). The Python packages had no findings. The scan
  is not one of the six required checks. `tests/unit/test_workflows.py` now lists `image-scan.yml` among the expected
  workflow files.
- Issue form "Work item (maintainers)" (`.github/ISSUE_TEMPLATE/work_item.yml`), for planned work with acceptance
  criteria, the way the portfolio's other repositories use it. The bug, feature and decision forms now also add the label
  `product:cloudcrawler`.
- **A documentation site on GitHub Pages, ready to switch on** (ticket #11). `scripts/build-pages.py` renders the
  README, `VALIDATION.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, the security policy and the ADRs into ten self-contained pages
  (one inline style sheet, no script, no external request, a viewport tag for phones, a dark theme) and then checks every
  internal link and `#fragment` in what it built; a broken one stops the build. Nothing is written twice, so the site says
  only what the repository says, and every page carries a "Not production" notice that matches `/api/health` reporting
  `production: false`. The new workflow `pages.yml` builds and checks on every pull request that touches those files, and
  deploys with `actions/configure-pages`, `actions/upload-pages-artifact` and `actions/deploy-pages` (pinned by commit, the
  `github-pages` environment, `pages: write` only in the deploy job) only on a push to `main` or a manual run and only when
  the repository variable `PAGES_ENABLED` is `true`. Until the owner enables Pages and sets that variable (README, "The
  documentation site"), the workflow publishes nothing and nothing becomes public. The build installs one new locked
  dependency group, `docs` (`markdown-it-py` 4.2.0, which `uv.lock` already held); it is not a default group, so the image
  and the engine are unchanged. The site has no separate pages yet for Installation, Configuration, Deployment,
  Operations, Testing or Troubleshooting: those are sections of the home page.

### Changed

- **`repository-admin.yml` can no longer lower the live rules by accident** (2026-10-25). Its `protect-main` and
  `protect-release-tags` tasks replace the whole ruleset with a list kept in the file, and that list was out of date:
  the live `Protect main` ruleset now needs one approving review, a code-owner review, approval of the last push and
  resolved review threads, and the live `Protect release tags` ruleset also blocks creating a tag and lets repository
  admins bypass it, while the file still said zero reviews and none of the rest. Running either task with "apply" would
  have switched all of that off without a word. Now both tasks read the live ruleset first and print what the update
  would remove or weaken and what it would add or change. With "apply" ticked they stop with an error, and change
  nothing, if the update would remove a rule, a required check, a bypass actor or a tag pattern, lower a number, or
  switch a protection off, unless the new "allow_weakening" box is ticked as well (it is off by default, and so is
  "apply"). A broken `REQUIRED_CHECKS` list (empty, not a list, a repeated or empty name) stops the task before
  anything is sent. The two payloads in the file now equal the live rulesets read on 2026-10-25 (the same six required
  checks as before), so an apply changes nothing today. New `tests/unit/test_repository_admin_required_checks.py`
  (51 tests): every required check must be a real job name in `ci.yml` or `security.yml` and equal an explicit list,
  the payloads must equal the live values, and the real step runs against a stand-in `gh` that answers from sample
  rulesets and records every call, including 16 one-setting-at-a-time weakenings that must each be refused. If you
  change the live ruleset, change `REQUIRED_CHECKS` and that test's lists in the same pull request. **Not verified: a
  real `protect-main` or `protect-release-tags` run (only the stand-in `gh` was used); after merging, run `show-plan`
  and `protect-main` without "apply" and check that both print "removes and weakens nothing".**
- Review round on the first pull request: `adr_create` refuses a claim its
  detector cannot evaluate (unknown detector, an expectation of the wrong
  shape, bad parameters) instead of failing every later `drift_evaluate`;
  `evidence_ingest` no longer takes `authenticated` from the caller, so
  handed-in evidence is always capped at 0.74 whatever its provenance
  claims; `CC_EVIDENCE_TTL_HOURS` now reaches observed evidence; the ledger
  closes an open contradiction as `fixed` when the same claim and resource
  evaluate `supported`; malformed private endpoint entries answer unknown;
  `gte`/`lte` expectations refuse booleans; `evidence_ingest` and
  `drift_evaluate` declare `idempotentHint: false`; every workflow checkout
  sets `persist-credentials: false`; the Dockerfile tolerates only the pip
  uninstall; the storage account naming exception is documented. The
  repository's own linters, as Qlty runs them, pass locally: bandit (the
  assert in `adr_accept` is an explicit check, the bind is annotated),
  yamllint (spaced one-line mappings allowed by `.yamllint.yaml`, long
  workflow lines wrapped), markdownlint and shellcheck.

- **Release pipeline (ticket #7, ticket #16).** One workflow, `publish-core.yml`, owns the whole release in one ordered path. It starts only for a tag of the exact form `vMAJOR.MINOR.PATCH` (a tag such as `vtest` or `v0.1.0-rc.1` starts nothing). `build` (read-only) runs the guard, builds the wheel and sdist with `--no-create-gitignore` (otherwise `dist/.gitignore` could become an attested subject; the flag exists in uv 0.11.32, the version the workflow installs), verifies the wheel, exports the SBOM with `uv export --locked`, and keeps the files, the release notes and a sha256 list as one workflow artifact. `attest` (the only job that can sign) attests provenance and the SBOM for the wheel and the sdist with `actions/attest` and verifies them, naming this workflow file, the tag and the commit (`--signer-workflow`, `--source-ref`, `--source-digest`), waiting up to about four minutes in total for a new attestation to become readable. `release` (the only job with repository write permission, for a tag only) checks the sha256 list, verifies the attestations again on the downloaded files, creates the GitHub Release as a draft with the three files, re-reads the draft by its id until all three are `uploaded`, checks that it holds exactly those files (and, where GitHub reports a sha256, that it matches; when GitHub reports none it says so, and integrity then rests on the sha256 list and the attestations), and only then makes it public. If any step fails nothing is public, and the job says how to remove a leftover draft. An existing release for the tag is never touched and no file is ever replaced. `pypi` runs only for a tag and only when `PYPI_ENABLED` is `true`. Every job has a time limit and every `gh` call is cut off after five minutes. The SBOM `cloud-crawler-core.cdx.json` is attested as a predicate of the wheel and the sdist, not as a subject of its own; the file on the release is covered by the sha256 list. The draft, publish and attestation steps live in `scripts/release-publish.py`.
- Dependencies: `pyjwt[crypto]==2.15.1` is now a direct, exactly pinned dependency of the appliance (host only, not the engine). It was already locked through the `mcp` SDK, so the resolved set is the same. `uv.lock` and `requirements.lock.txt` regenerated with `make lock`.
- `CLAUDE.md`: next ADR number is 0005.
- **Owner decisions of 2026-10-25 recorded** in [ADR 0004](docs/adr/0004-entra-token-validation-on-api-and-mcp.md), new section "Owner decisions": the `503` when the Entra signing keys cannot be fetched stays; `CC_AUTH_MODE=off` stays the default, with the warning and without a refusal to start; the loopback bind is the default and `0.0.0.0` only inside the image; any valid token for the configured tenant and audience may call the model tools (no client allow-list or role check yet). The README and `VALIDATION.md` now state these as decided, not open. No code changed. Ticket #8 stays open for the real-tenant check.
- `README.md`: the release section is a numbered checklist (changelog, mandatory dry run with attestations, pre-tag check, tag, check, first adoption in the AddOn, recovery) and says what the checks can and cannot do.
- `VALIDATION.md` records the checks run for the release on 2026-10-25 (tests, coverage, the appliance image, the SBOM, the action pins against the real tags, the workflow checks and the mutation check of the release tests) and what could not be run.
- AddOn note (for `HCW-CloudCrawler_AddOn`'s `docs/whats-new-upstream.md`, not edited from here): from `v0.1.0` the release carries a third asset, `cloud-crawler-core.cdx.json` (CycloneDX 1.5), and provenance and SBOM attestations for the wheel and sdist; the wheel's file name and URL pattern are unchanged, and `core-update.yml` needs no change. It stays inert until the AddOn's `pyproject.toml` has a `CORE_REF` line, so adopting `v0.1.0` is a first pin made by hand (README, "Adopting 0.1.0 in the AddOn"); the bump pull requests follow from then on. The release is made by one workflow, `publish-core.yml`, and the release page appears only once everything has been checked.

- Tests (ticket #13): the real-identifier scan in `tests/security/test_no_secrets.py` now asks git which files exist (`git ls-files --cached --others --exclude-standard`) instead of walking the folders, so ignored build output (bytecode caches, virtual environments) is never read, whatever the checkout path is. Where git is not available it falls back to the old walk with the same exclusions. What it catches is unchanged: the same folders, the same GUID rule, the same allow-list. Two new tests prove it: one plants a real-looking GUID in a throwaway git repository and in a checkout whose own folder name is a GUID (the scan must name it), and shows that an ignored cache holding the same GUID is not reported. Tests only; nothing reaches the lab edition.
- Coverage (ticket #17): `pyproject.toml` now omits test files (`*/tests/*`, `*/conftest.py`) from measurement, so `--cov=packages` no longer counts `packages/cloud-crawler-core/tests`. The honest figure, source files only, is 97.38 percent (233 tests). The minimum is raised from 85 to 96 percent in `pyproject.toml` and in the `--cov-fail-under` flag in `.github/workflows/ci.yml` (which overrides the file). New `tests/unit/test_main_entry.py` runs `python -m cloud_crawler_appliance` in-process: each of the five refused credential variables, a bad setting, the uvicorn start-up options, and the `__main__` guard (`__main__.py` 0 to 100 percent). `tests/unit/test_mcp_host.py` now covers the stdio host with a stand-in client (open, call, close, wrong or missing server version, error results) and the base host interface (`host.py` 79 to 99 percent). Tests and configuration only; nothing reaches the lab edition.
- `VALIDATION.md` re-run at `fc542be` on 2026-10-24 (218 tests, coverage 96.25 %, 59 files formatted, contract test, `pip-audit`, CI run 40101984078 including the `image` job). It now says plainly that the Dockerfile repeats the base image digest and does not read `infrastructure/docker/versions.env`, which is documentation only; the same note is in the header of `versions.env` (ticket #14). Documents only, so nothing reaches the lab edition.
- Dependencies: `httpx2` and `httpcore2` 2.15.1 → 2.16.0 in `uv.lock` and `requirements.lock.txt` (both arrive through the `mcp` SDK; `httpx2` requires one exact `httpcore2`). This replaces the open Dependabot pull requests #26 (`httpcore2`) and #27 (`httpx2`): each failed alone, `lint` because Dependabot does not regenerate `requirements.lock.txt` and `pip-audit` because the half-moved pair could not be installed. `.github/dependabot.yml` now groups the two. No public surface changed, so nothing reaches the lab edition. Verified: `make lint`, `uv run pytest -q --cov=packages --cov=src` (218 passed, coverage 96.25 %), `make test-contract` (1 passed against the real Azure MCP Server 3.0.0) and `pip-audit -r requirements.lock.txt --strict` (no known vulnerabilities).
- Dependencies: `pydantic` 2.14.0 → 2.14.1 (the exact pin in `pyproject.toml`) with `pydantic-core` 2.50.0 → 2.50.1 in `uv.lock` and `requirements.lock.txt`. This replaces the open Dependabot pull requests #3 and #4: #4 (`pydantic-core` alone) could not resolve because pydantic pins its core to one exact version. `.github/dependabot.yml` now groups `pydantic` and `pydantic-core` so they arrive in one pull request. The engine package's `pydantic>=2.14,<3` range is unchanged, so nothing reaches the lab edition. Verified: `make lint`, `uv run pytest -q --cov=packages --cov=src` (218 passed, coverage 96.25 %) and `make test-contract` (1 passed against the real Azure MCP Server 3.0.0).

- README: the repository layout lists `repository-admin`, and release step 1 now matches the changelog as it stands (the `## [0.1.0]` section already exists and
  nothing is tagged yet, so the `[Unreleased]` entries are folded into it on release day).
- `infrastructure/README.md` says plainly that the Dockerfile repeats the digest from `versions.env` and that nothing compares the two (ticket #14).
- `VALIDATION.md` re-run from `main` at `697cdc4` on 2026-10-24 (218 tests, coverage 96.25 percent, contract test and pip-audit clean, CI runs on that commit).
- `CLAUDE.md`: when a change reaches the AddOn, add an entry to the AddOn's `docs/whats-new-upstream.md` in the same change set, or say in the pull request why not.
- `codeql.yml` and `dependency-review.yml` use the same runner label as every other workflow (`ubuntu-26.04`, not `ubuntu-latest`). `publish-core.yml` no
  longer passes `--clobber`: attaching the wheel and sdist to a release fails if a file of the same name is already there, so a re-run cannot silently
  replace published files. It also writes a CycloneDX SBOM of the engine's locked runtime dependencies (`uv export --format cyclonedx1.5`), attaches it to
  the release and attests it with `actions/attest` v4.2.2 (SHA-pinned). Part of ticket #16.
- `VALIDATION.md` re-run from `main` at `fed357b` on 2026-10-24: current file counts, test and coverage numbers, CI evidence for the image job and the
  security workflows, no `v0.1.0` tag yet, the missing sign-in on `/api` and `/mcp` recorded as a limitation, and the dead reference to
  `docs/TEMPLATE.md` removed (ticket #14).
- `CLAUDE.md`: the form-filling rule now says secrets are never written in chat, pull requests, issues or documentation; the owner enters each secret
  only in the secure settings field or through a script that reads it from a file.
- **Leftover repository-template content removed or rewritten** (ticket #12). `.github/CODEOWNERS` lists the real owner
  and no placeholders. The folder `.github/templates/` (blog, gist, task and workflow-document templates) and the
  FinOps-finding and infrastructure-change issue forms were deleted: nothing here uses them. `CONTRIBUTING.md` now
  describes this repository (its commands, the pinned Azure MCP Server, the changelog rule, the plain-language rule, the
  AddOn rule, the image scan) instead of generic Terraform guidance. The pull request template's "Infrastructure changes
  only" section became "Image or workflow changes only" and gained the AddOn and changelog check boxes;
  `.github/copilot-instructions.md` no longer asks for Terraform plans. The README no longer says the repository was
  created from a template. The reminder to re-resolve the base image digest in `infrastructure/docker/versions.env` is
  resolved: the pinned digest still resolves to `python:3.14.8-slim-trixie` (checked 2026-10-25), and the file records that
  the tag has since been rebuilt, so moving the pin is a separate, reviewed change.

### Fixed

- `ci.yml`: the step that runs the tests was still named "85 percent coverage gate" although the gate has been 96 percent since ticket #17; the name and the header comment now say 96, and a test keeps the name, the flag and `pyproject.toml` in step.
- `tests/security/test_no_secrets.py`: the real-identifier scan no longer reads compiled bytecode caches (`__pycache__`, `.pyc`, `.pyo`). They embed the
  checkout's absolute path, so a checkout whose path contained a GUID (a temporary or CI directory) failed `test_no_real_guids_outside_placeholders`
  with dozens of false hits. The scan of source files is unchanged, and a new test proves both halves: caches are skipped, and a real-looking GUID in a
  source file is still reported (ticket #13).
