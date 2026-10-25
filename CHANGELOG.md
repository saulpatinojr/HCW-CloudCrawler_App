# Changelog

All notable changes to this repository are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) where it versions
anything.

Add an entry under **Unreleased** in the same pull request as the change.
Several open pull requests collide on this section, so when two are open at
once, merge one before rebasing the next.

## [Unreleased]

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
