# Changelog

All notable changes to this repository are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) where it versions
anything.

Add an entry under **Unreleased** in the same pull request as the change.
Several open pull requests collide on this section, so when two are open at
once, merge one before rebasing the next.

## [Unreleased]

### Security

- Microsoft Entra sign-in for `/api` and `/mcp` (ticket #8, [ADR 0004](docs/adr/0004-entra-token-validation-on-api-and-mcp.md)). With `CC_AUTH_MODE=entra` every route except `GET /api/health` needs a valid Entra access token: RS256 signature against the tenant's signing keys (JWKS, fetched over HTTPS with a timeout and a short cache), `iss` (v2.0 and v1.0 forms), `aud`, `exp` and `nbf` with a declared clock skew, and `tid`. A failure is `401` with `WWW-Authenticate: Bearer` and the usual error shape; unreachable signing keys are `503`. The token and its claims are never logged. The human-only tools (`adr_accept`, `review_decide`, `collection_run_azure`) take the actor from the token's `oid`, need a person's delegated token (scope `access_as_user`, not an app-only token), and refuse a typed `actorId` that differs; `adr_create` records the token as author. New settings: `CC_AUTH_MODE`, `CC_ENTRA_TENANT_ID`, `CC_ENTRA_AUDIENCE`, `CC_ENTRA_HUMAN_SCOPE`, `CC_ENTRA_CLOCK_SKEW_SECONDS`, `CC_ENTRA_JWKS_CACHE_SECONDS`, `CC_BIND_HOST` (all in `.env.example`). The default is still `off`: a lab-only warning stays in the README. Entra settings with sign-in off, or `entra` without a tenant or audience, stop the start-up. Not tested against a real tenant (`VALIDATION.md`). The engine package is unchanged; the tool schemas make `actorId` optional, which the AddOn's `docs/whats-new-upstream.md` should record.
- The server binds `127.0.0.1` unless `CC_BIND_HOST` is set; the container image sets `CC_BIND_HOST=0.0.0.0`, so the image listens as before. `/api/health` reports `auth`.

### Changed

- Dependencies: `pyjwt[crypto]==2.15.1` is now a direct, exactly pinned dependency of the appliance (host only, not the engine). It was already locked through the `mcp` SDK, so the resolved set is the same. `uv.lock` and `requirements.lock.txt` regenerated with `make lock`.
- `CLAUDE.md`: next ADR number is 0005.

- Tests (ticket #13): the real-identifier scan in `tests/security/test_no_secrets.py` now asks git which files exist (`git ls-files --cached --others --exclude-standard`) instead of walking the folders, so ignored build output (bytecode caches, virtual environments) is never read, whatever the checkout path is. Where git is not available it falls back to the old walk with the same exclusions. What it catches is unchanged: the same folders, the same GUID rule, the same allow-list. Two new tests prove it: one plants a real-looking GUID in a throwaway git repository and in a checkout whose own folder name is a GUID (the scan must name it), and shows that an ignored cache holding the same GUID is not reported. Tests only; nothing reaches the lab edition.
- Coverage (ticket #17): `pyproject.toml` now omits test files (`*/tests/*`, `*/conftest.py`) from measurement, so `--cov=packages` no longer counts `packages/cloud-crawler-core/tests`. The honest figure, source files only, is 97.38 percent (233 tests). The minimum is raised from 85 to 96 percent in `pyproject.toml` and in the `--cov-fail-under` flag in `.github/workflows/ci.yml` (which overrides the file). New `tests/unit/test_main_entry.py` runs `python -m cloud_crawler_appliance` in-process: each of the five refused credential variables, a bad setting, the uvicorn start-up options, and the `__main__` guard (`__main__.py` 0 to 100 percent). `tests/unit/test_mcp_host.py` now covers the stdio host with a stand-in client (open, call, close, wrong or missing server version, error results) and the base host interface (`host.py` 79 to 99 percent). Tests and configuration only; nothing reaches the lab edition.
- `VALIDATION.md` re-run at `fc542be` on 2026-10-24 (218 tests, coverage 96.25 %, 59 files formatted, contract test, `pip-audit`, CI run 40101984078 including the `image` job). It now says plainly that the Dockerfile repeats the base image digest and does not read `infrastructure/docker/versions.env`, which is documentation only; the same note is in the header of `versions.env` (ticket #14). Documents only, so nothing reaches the lab edition.
- Dependencies: `httpx2` and `httpcore2` 2.15.1 → 2.16.0 in `uv.lock` and `requirements.lock.txt` (both arrive through the `mcp` SDK; `httpx2` requires one exact `httpcore2`). This replaces the open Dependabot pull requests #26 (`httpcore2`) and #27 (`httpx2`): each failed alone, `lint` because Dependabot does not regenerate `requirements.lock.txt` and `pip-audit` because the half-moved pair could not be installed. `.github/dependabot.yml` now groups the two. No public surface changed, so nothing reaches the lab edition. Verified: `make lint`, `uv run pytest -q --cov=packages --cov=src` (218 passed, coverage 96.25 %), `make test-contract` (1 passed against the real Azure MCP Server 3.0.0) and `pip-audit -r requirements.lock.txt --strict` (no known vulnerabilities).
- Dependencies: `pydantic` 2.14.0 → 2.14.1 (the exact pin in `pyproject.toml`) with `pydantic-core` 2.50.0 → 2.50.1 in `uv.lock` and `requirements.lock.txt`. This replaces the open Dependabot pull requests #3 and #4: #4 (`pydantic-core` alone) could not resolve because pydantic pins its core to one exact version. `.github/dependabot.yml` now groups `pydantic` and `pydantic-core` so they arrive in one pull request. The engine package's `pydantic>=2.14,<3` range is unchanged, so nothing reaches the lab edition. Verified: `make lint`, `uv run pytest -q --cov=packages --cov=src` (218 passed, coverage 96.25 %) and `make test-contract` (1 passed against the real Azure MCP Server 3.0.0).

### Added

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

### Changed

- README: the repository layout lists `repository-admin`, and release step 1 now matches the changelog as it stands (the `## [0.1.0]` section already exists and
  nothing is tagged yet, so the `[Unreleased]` entries are folded into it on release day).
- `infrastructure/README.md` says plainly that the Dockerfile repeats the digest from `versions.env` and that nothing compares the two (ticket #14).
- `VALIDATION.md` re-run from `main` at `697cdc4` on 2026-10-24 (218 tests, coverage 96.25 percent, contract test and pip-audit clean, CI runs on that commit).
- `CLAUDE.md`: when a change reaches the AddOn, add an entry to the AddOn's `docs/whats-new-upstream.md` in the same change set, or say in the pull request why not.
- `codeql.yml` and `dependency-review.yml` use the same runner label as every other workflow (`ubuntu-26.04`, not `ubuntu-latest`). `publish-core.yml` no
  longer passes `--clobber`: attaching the wheel and sdist to a release fails if a file of the same name is already there, so a re-run cannot silently
  replace published files. It also writes a CycloneDX SBOM of the engine's locked runtime dependencies (`uv export --format cyclonedx1.5`), attaches it to
  the release and attests it with `actions/attest` v4.2.2 (SHA-pinned). The release path itself has not run yet; it first runs on the `v0.1.0` tag
  (ticket #7). Part of ticket #16.
- `VALIDATION.md` re-run from `main` at `fed357b` on 2026-10-24: current file counts, test and coverage numbers, CI evidence for the image job and the
  security workflows, no `v0.1.0` tag yet, the missing sign-in on `/api` and `/mcp` recorded as a limitation, and the dead reference to
  `docs/TEMPLATE.md` removed (ticket #14).
- `CLAUDE.md`: the form-filling rule now says secrets are never written in chat, pull requests, issues or documentation; the owner enters each secret
  only in the secure settings field or through a script that reads it from a file.

### Fixed

- `tests/security/test_no_secrets.py`: the real-identifier scan no longer reads compiled bytecode caches (`__pycache__`, `.pyc`, `.pyo`). They embed the
  checkout's absolute path, so a checkout whose path contained a GUID (a temporary or CI directory) failed `test_no_real_guids_outside_placeholders`
  with dozens of false hits. The scan of source files is unchanged, and a new test proves both halves: caches are skipped, and a real-looking GUID in a
  source file is still reported (ticket #13).

### Security

## [0.1.0] - 2026-10-21

The first release of the engine `cloud-crawler-core` 0.1.0 and the App edition 0.1.0, as merged in
[saulpatinojr/HCW-CloudCrawler_App#2](https://github.com/saulpatinojr/HCW-CloudCrawler_App/pull/2). The release
workflows attach the engine wheel the AddOn adopts (ADR 0002).

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
  - The release pipeline (ADR 0002): `release.yml` creates the GitHub
    Release for a `v*` tag from the changelog section after checking the
    tag matches the engine version; `publish-core.yml` builds the engine
    wheel and sdist, verifies the wheel with `scripts/verify-core-wheel.py`
    (the engine present, no cloud SDK, no HTTP client, no Azure endpoint,
    pydantic the only requirement), attests provenance and attaches both,
    which is what the AddOn's `core-update.yml` pins.
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

### Changed

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

### Fixed

### Security
