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

### Fixed

### Security
