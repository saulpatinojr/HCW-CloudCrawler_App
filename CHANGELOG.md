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

- `CLAUDE.md`: owner-communication rule to give the exact text for every form field, always with a description.

- `CLAUDE.md`: a communication-style section (plain language, junior-administrator audience, step-by-step
  instructions, links).

### Changed

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
