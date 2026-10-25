# Contributing

Thank you for helping. This guide says how a change gets from your machine into `main` in this repository, the **App
edition** of Cloud Crawler (an evidence ledger, decision records, deterministic drift detection and review proposals
built around Azure MCP Server 3.0.0). `CLAUDE.md` holds the working agreement that an AI coding agent follows; people
and agents follow the same rules. `README.md` is the overview.

## Before you start

- Search the existing issues and pull requests first.
- For anything bigger than a small fix, open an issue from the **New issue** page (use a form) so the outcome and the
  acceptance criteria are agreed before you write code.
- Never put credentials, tokens, private keys, connection strings, personal data, customer inventories, or real tenant
  or subscription identifiers in code, tests, fixtures, logs, issues or pull requests. Samples use the subscription
  `00000000-0000-0000-0000-000000000001` and `hcw-sample-*` names only.
- A vulnerability is not an issue. Report it privately as `.github/SECURITY.md` describes.
- By taking part you agree to the [code of conduct](CODE_OF_CONDUCT.md). The project is MIT-licensed ([LICENSE](LICENSE)).

## What lives where

| Path | What |
| --- | --- |
| `packages/cloud-crawler-core/` | The engine: models, detectors, drift, ledger, redaction. It moves downstream **unchanged** to the AddOn repository ([ADR 0002](docs/adr/0002-engine-moves-downstream-unchanged.md)). |
| `src/cloud_crawler_appliance/` | The appliance: edition guard, settings, logging, Entra sign-in, MCP server, HTTP API, Azure MCP host. |
| `tests/` | Unit, security, acceptance and contract suites (the engine also has tests under its own folder). |
| `infrastructure/docker/` | The appliance image and its pinned base image. |
| `.github/workflows/` | CI, security scans, the weekly image scan, CodeQL, dependency review and the release workflows. |
| `docs/adr/` | Decision records. Copy `docs/adr/template.md`; the next number is 0005. |

## Set up and check your change

You need Python 3.14.6 (the repository pins it) and [uv](https://docs.astral.sh/uv/). Node.js 22 is needed only for the
Azure MCP contract test. The `Makefile` targets run in bash; on Windows, run the `uv run ...` lines in PowerShell
directly (they are the same commands).

```bash
uv sync --frozen --all-packages
uv run --frozen ruff check .
uv run --frozen ruff format --check .
bash scripts/check-lockfiles.sh
uv run --frozen pytest -q --cov=packages --cov=src --cov-fail-under=96
```

`make lint` and `make test` run the same checks (`make lint` also runs `scripts/check-release-version.py`, which checks
that every file naming the release version agrees). Two more commands for specific changes:

- `make test-contract` starts the real Azure MCP Server 3.0.0 through `npx` (network needed, no Azure sign-in). Run it
  for anything that touches the Azure MCP contract.
- `bash scripts/scan-image.sh` builds the appliance image and scans it with Trivy, the same way the weekly workflow
  does. It needs Docker (on Windows, Docker Desktop with the `desktop-linux` context) and nothing else.

Say in your pull request which of these you ran and what each result proves. Do not report a check you did not run.

## Rules that are easy to get wrong

- **Azure MCP Server stays at 3.0.0** ([ADR 0001](docs/adr/0001-pin-azure-mcp-server-3-0-0.md)). The file
  `tests/contract/snapshots/azmcp-3.0.0-tools.json` is the contract; regenerate it only with `CC_UPDATE_SNAPSHOT=1`,
  locally, in a reviewed change that says why. Never substitute a 4.x beta.
- **Never weaken** the startup refusal when a client secret or password is in the environment, the content-free log
  writer, payload redaction at ingest, the "not an audit" bundle text, or `callsAzure: false` on tools that do not call
  Azure. `CLAUDE.md` lists them in full. No client-secret credential class belongs anywhere in `src` or `packages`.
- **Engine rules:** pydantic only (no HTTP client, no cloud SDK, no I/O); verdicts come from detectors, never from a
  model; an unknown answer lowers coverage, never the score; detector ids and evidence kinds are only added, never
  renamed.
- **Dependencies are locked.** After you change `pyproject.toml`, run `uv lock` (or `make lock`, which also rewrites
  `requirements.lock.txt`, the hash-pinned set the image installs) and commit both files. Never edit them by hand.
- **Workflows:** every `uses:` is a full commit SHA with the version in a trailing comment, every runner is
  `ubuntu-26.04`, and every workflow starts with `permissions: contents: read`. `tests/unit/test_workflows.py` pins the
  exact set of workflow files and these rules, so adding a workflow means adding its name to that test.
- **The image scan's accepted-risk file.** `.trivyignore.yaml` lists base-image vulnerabilities that have no fix and
  that the owner chose to live with. Every entry needs an id, a reason, an owner and an expiry date, and
  `tests/unit/test_image_scan.py` fails when one is missing or past its date. A finding that has a fix is never
  accepted: update the base image instead. The README section "Image scan and accepted risk" explains the renewal steps.

## Pull requests

- Branch from the current `main` and keep each pull request to one purpose. Pull requests open ready for review.
- Fill in the pull request template (GitHub shows it when you open the pull request): the commands you ran and what each proves, the checks you did not run and
  why, and whether the evidence is static, local or from CI.
- `main` is protected by a ruleset: changes arrive through a pull request and the six checks `lint`, `test`,
  `contract`, `pip-audit`, `secret-scan` and `image` must pass. Do not push straight to `main` and do not merge while a
  check, a review or a security finding is open.
- **Update `CHANGELOG.md` in the same pull request.** Add the entry under `## [Unreleased]` (written for a person who was
  not there: what changed and why it matters). The release workflows read this file, so see the README section
  "Releasing the engine" before a release.
- **Keep the AddOn informed.** The AddOn repository (`saulpatinojr/HCW-CloudCrawler_AddOn`) adopts the engine from here.
  If your change reaches it (the public surface of `packages/cloud-crawler-core`, tool schemas, detector ids, evidence
  kinds, the release workflows or their assets, the shared test rules), add an entry to the AddOn's
  `docs/whats-new-upstream.md` in the same change set, or say in the pull request why none is needed.
- Record limitations of what you could not test in `VALIDATION.md`, and decisions in an ADR.
- Add or update tests with the change, including the failure and denial paths. A test that cannot fail proves nothing.

## Writing for the owner and for future readers

Write issues, pull requests and documentation in plain, friendly language for a junior administrator who has no memory
of earlier work: say what a thing is the first time it appears, explain a technical term in a few words, and when a
person must act, give numbered steps that name the shell (bash or PowerShell) and what they should see. Give exact
values for every form field and never write a secret in chat, an issue, a pull request or a document. Be honest about
status: separate what was checked, what is assumed and what is blocked. `CLAUDE.md` has the full rule. Code comments
and machine-readable files keep following the style around them.
