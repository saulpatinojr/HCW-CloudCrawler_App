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
Azure credential. Today the App edition starts the server as a child process
over stdio with the developer's own credential chain (the development model);
running under a managed identity, or forwarding a user's delegated token
through Azure MCP's on-behalf-of flow, is planned with the HTTP transport.
The AddOn edition cannot reach Azure at all (ADR 0003).

## Is there a user interface?

No, and that is by design for now. This App edition has no screens of its own: it is an HTTP API (`/api/health`)
and an MCP server (`/mcp`) that other programs call, and nothing in this repository serves a web page. The screens
people use live elsewhere, in the owner-approved design (the website repository's proposal *Azure Architecture MCP
Appliance on Azure MCP Server 3.0*, sections 7, 9 and 17):

- **The website** (hybridcloudworks.com) owns sign-in, the tenant and subscription pickers, the chat, the evidence
  and drift views and the approvals. The proposal's feature table calls this "Lab page ... Website only".
- **The AddOn** ([`HCW-CloudCrawler_AddOn`](https://github.com/saulpatinojr/HCW-CloudCrawler_AddOn)) carries a small
  web pane (its `web/` folder) that the website frames. It never calls Azure.
- **This App edition** may one day carry its own sign-in and chat loop for an "enterprise package": the proposal
  marks both as optional and for that package only. Neither is built here.

Until the owner decides to build that enterprise package, treat this repository as headless.

## Status

First implementation slice. What exists today:

- the engine's evidence, provenance, collection-run, decision, claim, drift,
  contradiction and review models, canonical hashing and redaction;
- the Azure Resource Graph export normaliser (JSON array export);
- the Azure MCP host (`src/cloud_crawler_appliance/mcp_host`): Azure MCP
  Server 3.0.0 as a child process over stdio (the development model, the
  developer's own credential chain, nothing held by the appliance) or a
  recorded host that replays the fictional results in `samples/azure-mcp`;
  a read-only tool allow-list the contract test proves against the pinned
  snapshot; the result-to-evidence mapping (tool, server, version, protocol,
  parameter hashes, subject) and the standard collection sequence;
- the Azure observation detectors `advisor-findings` (a `New` record is a
  contradiction; `Dismissed` and `Postponed` are accepted risk),
  `retirement-exposure` (opens a retirement proposal with the date and the
  Advisor remediation) and `policy-assignment-present`;
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
  model, `review_propose`, the human-only `adr_accept` and `review_decide`,
  which take a person's object id and store only its hash (every tool
  carries `meta.caller`), and, only when a host is configured, the Full-only
  `collection_run_azure`, the one tool with `meta.callsAzure: true`; and a
  flat `/api/health` whose `azureConnectivity` names the host mode;
- a contract test that starts the real Azure MCP Server 3.0.0 over stdio and
  snapshots its tool list, so an unreviewed upgrade fails the build;
- three acceptance scenarios, in-process and over streamable HTTP: the
  zone-redundancy contradiction, the six-claim "production platform
  baseline" over every wave-one detector, and the Azure observations
  (retirement review generation, Advisor contradiction with accepted risk,
  policy assignment) through `collection_run_azure` on the recorded host.

Not yet: the HTTP transport to a hosted Azure MCP (managed identity or
on-behalf-of), live collectors beyond the standard sequence, the persistent
ledger, the `cost-ceiling` detector, the operator pane, Container Apps
deployment.
The roadmap is section 22 of the proposal; nothing here is production.

## Getting started

Prerequisites: Python 3.14 (managed by `uv`), `uv` 0.11, Node.js 22 for the
contract test (it runs `npx @azure/mcp@3.0.0`).

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest -q --cov=packages --cov=src
```

Run the appliance locally (no Azure access is needed):

```bash
uv run python -m cloud_crawler_appliance
```

With the recorded Azure MCP host, so `collection_run_azure` replays the
fictional results in `samples/azure-mcp`:

```bash
CC_AZMCP_MODE=recorded uv run python -m cloud_crawler_appliance
```

With the real Azure MCP Server 3.0.0 as a child process over stdio (the
development model; Node.js 22, `az login` first; every call is read-only and
the appliance never sees a token):

```bash
AZURE_TOKEN_CREDENTIALS=AzureCliCredential CC_AZMCP_MODE=stdio uv run python -m cloud_crawler_appliance
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

## Releasing the engine

The AddOn adopts the engine as the wheel attached to a GitHub Release of
this repository, pinned by URL and sha256 (ADR 0002; the AddOn's
`core-update.yml` opens the bump pull request). A release is one tag:

1. `CHANGELOG.md` already has a `## [0.1.0]` section, dated 2026-10-21 when the release was first prepared.
   `v0.1.0` has not been tagged yet (no tag and no release exist), so everything under `[Unreleased]` ships with
   it: fold those entries into the `## [0.1.0]` section and set its date to the release day (`release.yml` takes
   the release notes from that section). Keep `packages/cloud-crawler-core/pyproject.toml` at the same version
   (`release.yml` refuses a tag that does not match it).
2. Tag `main` and push the tag. PowerShell:

```powershell
git switch main; git pull origin main; git tag -a v0.1.0 -m "cloud-crawler-core 0.1.0"; git push origin v0.1.0
```

`release.yml` creates the release from the changelog section; `publish-core.yml`
builds the wheel and sdist, verifies the wheel with
`scripts/verify-core-wheel.py` (the engine, no cloud SDK, no HTTP client,
no Azure endpoint, pydantic as its only requirement), attests provenance
and attaches both. A successful run shows two assets on
`https://github.com/saulpatinojr/HCW-CloudCrawler_App/releases/tag/v0.1.0`:
`cloud_crawler_core-0.1.0-py3-none-any.whl` and `cloud_crawler_core-0.1.0.tar.gz`.
Within six hours the AddOn's `core-update.yml` opens its bump pull request;
`gh workflow run core-update.yml --repo saulpatinojr/HCW-CloudCrawler_AddOn`
(bash or PowerShell) runs it at once.

## Repository layout

```text
packages/cloud-crawler-core/   the engine: models, normalise, detectors, drift, ledger, redaction, hashing
src/cloud_crawler_appliance/   the appliance application: edition guard, config, logging, MCP server, HTTP API,
                               and mcp_host/ (the client of Azure MCP Server: contract, stdio and recorded hosts, collection)
tests/                         unit, security, contract (Azure MCP 3.0.0 snapshot) and acceptance suites
samples/                       fictional Resource Graph exports, decisions and recorded Azure MCP results
                               (subscription 00000000-0000-0000-0000-000000000001)
infrastructure/docker/         the hardened Dockerfile and the pinned base image
scripts/                       the lockfile check and the release wheel verifier
.github/workflows/             ci, security, codeql, dependency-review, release, publish-core, repository-admin
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
  `AZURE_CLIENT_CERTIFICATE_PASSWORD`,
  `AZURE_USERNAME`, `AZURE_PASSWORD`).
- Logs are content-free: counts, durations, flags and hashed identifiers.
- Azure MCP Server stays at 3.0.0 until an ADR records the upgrade criteria
  being met (ADR 0001).

## Branch and tag protection

Two GitHub rulesets protect this repository. They are applied by the owner-approved `repository-admin` workflow
(tasks `protect-main` and `protect-release-tags`) and can be checked under Settings, Rules, Rulesets:

- **Protect main:** `main` cannot be deleted or force-pushed, changes arrive through a pull request, and the six
  checks `lint`, `test`, `contract`, `pip-audit`, `secret-scan` and `image` must pass.
- **Protect release tags:** a `v*` tag cannot be moved or deleted once pushed. Check the version before tagging.

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
