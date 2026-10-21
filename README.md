# HCW Cloud Crawler, App edition

[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Cloud Crawler is Hybrid Cloud Works' Azure architecture appliance: an evidence
ledger, architecture decision records, deterministic drift detection and
review proposals, with **Azure MCP Server 3.0** as the source of truth for what
Azure reports and this appliance as the source of truth for what was decided,
claimed, contradicted, reviewed and approved.

This repository is the **upstream product**. It owns the engine
(`packages/cloud-crawler-core`), the appliance application
(`src/cloud_crawler_appliance`) and, in later releases, the Azure MCP host,
the live collectors, the persistent ledger and the Container Apps deployment.
It is the reference implementation, the enterprise deployment option and the
proving ground. It is **not** integrated into hybridcloudworks.com: the site
integrates only with the derived lab edition,
[`HCW-CloudCrawler_AddOn`](https://github.com/saulpatinojr/HCW-CloudCrawler_AddOn),
which adopts the engine from here unchanged.

The design this repository implements is the owner-approved proposal
*Azure Architecture MCP Appliance on Azure MCP Server 3.0* in the website
repository (`docs/architecture/azure-architecture-mcp-appliance.md`). Its
decisions that bind this repository are recorded as ADRs in `docs/adr/`.

## What it does

| Record | Meaning |
| --- | --- |
| **Evidence** | What Azure reported (Observed), what an artifact says (Imported), what a decision states (Declared), what was derived or inferred, and what is proposed. Every record is hashed, redacted and carries provenance and an expiry. |
| **Decision record** | An ADR with context, drivers, alternatives, consequences and **claims**, each claim bound to a deterministic detector. |
| **Drift finding** | The verdict of one claim against current evidence: `supported`, `contradicted`, `unknown` or `not-applicable`. Unknown lowers coverage, never score. |
| **Contradiction** | An open, dated record that a claim is contradicted by evidence, with the evidence ids. |
| **Review proposal** | What a contradiction, a retirement notice, an Advisor finding or a cost ceiling asks the architects to decide, with an approval trail. |

Azure MCP Server is consumed as a separate process, pinned to **3.0.0**
(ADR 0001). The appliance never links it, never forks it and never stores an
Azure credential: the App edition runs under a managed identity or forwards
a user's delegated token through Azure MCP's on-behalf-of flow; the AddOn
edition cannot reach Azure at all (ADR 0003).

## Status

First implementation slice. What exists today:

- the engine's evidence, provenance, collection-run, decision, claim, drift,
  contradiction and review models, canonical hashing and redaction;
- the Azure Resource Graph export normaliser (JSON array export);
- the wave-one detectors: `zone-redundancy` (SQL databases, storage accounts,
  App Service plans, PostgreSQL flexible servers, Cosmos DB accounts, AKS
  clusters, virtual machine scale sets and public IP addresses; a single
  virtual machine row answers `unknown`, because redundancy is a property of
  the instance set), `public-access-disabled` and `private-endpoint-present`
  (twelve data, secret, messaging and compute types), `managed-identity`,
  and the valued `tag-required`, `sku-allowed` and `region-allowed`, whose
  claims compare the reading with `exists`, `in`, `eq` and the like;
- the drift engine and the in-memory ledger;
- an MCP server (streamable HTTP, stateless) with the proposal's catalogue
  minus the Full-only tools: `adr_create`, `adr_get`, `adr_list`,
  `evidence_ingest`, `evidence_list`, `evidence_get`, `drift_evaluate`,
  `drift_list`, `contradiction_list`, `review_list` and `review_get` for the
  model, and the human-only `adr_accept` and `review_decide`, which take a
  person's object id and store only its hash (every tool carries
  `meta.caller` and `meta.callsAzure: false`); and a flat `/api/health`;
- a contract test that starts the real Azure MCP Server 3.0.0 over stdio and
  snapshots its tool list, so an unreviewed upgrade fails the build;
- two acceptance scenarios against the fictional sample estate, in-process
  and over streamable HTTP: the zone-redundancy contradiction, and the
  six-claim "production platform baseline" over every wave-one detector.

Not yet: the Azure MCP host, live collectors, the persistent ledger, the
Advisor, retirement and policy detectors, `review_propose` for retirements,
the operator pane, Container Apps deployment.
The roadmap is section 22 of the proposal; nothing here is production.

## Getting started

Prerequisites: Python 3.14 (managed by `uv`), `uv` 0.11, Node.js 22 for the
contract test (it runs `npx @azure/mcp@3.0.0`).

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest -q --cov=packages --cov=src
```

Run the appliance locally (no Azure access is needed for this slice):

```bash
uv run python -m cloud_crawler_appliance
```

Then `GET http://127.0.0.1:8080/api/health` answers a flat document with `id`,
`version` and `edition` at the top level, and the MCP endpoint is
`http://127.0.0.1:8080/mcp`.

Run the Azure MCP contract test on its own (needs network for the npm
download; no Azure sign-in, because only `initialize` and `tools/list` are
sent):

```bash
uv run pytest tests/contract -q -m azmcp
```

## Repository layout

```text
packages/cloud-crawler-core/   the engine: models, normalise, detectors, drift, ledger, redaction, hashing
src/cloud_crawler_appliance/   the appliance application: edition guard, config, logging, MCP server, HTTP API
tests/                         unit, security, contract (Azure MCP 3.0.0 snapshot) and acceptance suites
samples/                       fictional Resource Graph exports (subscription 00000000-0000-0000-0000-000000000001)
infrastructure/docker/         the hardened Dockerfile and the pinned base image
docs/adr/                      this edition's decisions
```

## Rules that do not bend

- No secrets, tokens, customer inventories or real tenant, subscription or
  resource identifiers anywhere, fixtures and tests included. Samples use
  subscription `00000000-0000-0000-0000-000000000001` and `hcw-sample-*`
  names only.
- The engine depends on pydantic only: no HTTP client, no cloud SDK. It moves
  downstream to the AddOn unchanged (ADR 0002).
- Verdicts come from detectors, never from a model. Unknown lowers coverage,
  never score. Detector ids are only ever added, never renamed.
- The appliance refuses to start when a secret-bearing credential variable is
  present (`AZURE_CLIENT_SECRET`, `AZURE_CLIENT_CERTIFICATE_PATH`,
  `AZURE_USERNAME`, `AZURE_PASSWORD`).
- Logs are content-free: counts, durations, flags and hashed identifiers.
- Azure MCP Server stays at 3.0.0 until an ADR records the upgrade criteria
  being met (ADR 0001).

## Repository standards

This repository was created from the organisation's template repository. It
carries `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`,
`.github/SECURITY.md`, `.github/CODEOWNERS`, the pull request and issue
templates, CodeQL, dependency review, Dependabot, CodeRabbit and Qlty
configuration, and `docs/adr/`. Pull requests open ready for review and follow
`.github/PULL_REQUEST_TEMPLATE.md`; `CHANGELOG.md` is updated in the same pull
request as the change.

## Contributing, security, license

See `CONTRIBUTING.md`, `.github/SECURITY.md` and [LICENSE](LICENSE) (MIT).
