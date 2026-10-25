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
  which store only the hash of a person's object id (typed by the caller with
  sign-in off, taken from the Microsoft Entra token with sign-in on; every tool
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

Also today: optional Microsoft Entra sign-in on `/api` and `/mcp` (ADR 0004, off by
default; see "Signing in with Microsoft Entra" below).

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

## Signing in with Microsoft Entra

**Interim note: with sign-in off, which is the default, nobody is asked who they are.** Anyone who can reach the
port can read evidence and accept decisions as if they were a trusted person. Run the appliance only on a trusted lab
network until you turn sign-in on. Turning it on is a decision recorded in
[ADR 0004](docs/adr/0004-entra-token-validation-on-api-and-mcp.md). The defaults described here are decided, not open
(the owner's answers of 2026-10-25 are in that ADR's "Owner decisions" section): sign-in stays off by default, with the
warning below, and the appliance does not refuse to start without it.

Two things make the default less exposed than it used to be. The server now listens on `127.0.0.1` (this machine
only) unless `CC_BIND_HOST` says otherwise; the container image sets `CC_BIND_HOST=0.0.0.0`, so the image still
listens on every interface. And if it starts unauthenticated on a non-loopback address, it writes one `warning` line.
`GET /api/health` reports `"auth": "off"` or `"auth": "entra"` so you can see which one is running.

### What sign-in does

With `CC_AUTH_MODE=entra`, every route except `GET /api/health` needs `Authorization: Bearer <access token>` from
your Microsoft Entra tenant. The appliance checks the token's signature against your tenant's published signing keys
(RS256 only), its issuer, audience, expiry and not-before time (with a small clock skew), and that it was issued by
your tenant. Anything else gets `401` with `WWW-Authenticate: Bearer` and `{"error": {"code", "message"}}`; if the
signing keys cannot be fetched it answers `503` and tries again later (decided: an outage is the server's fault, so it
is not a `401`, and the request is never let through). Nothing about the token is logged or stored.
Background: [access tokens](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens) and
[claims validation](https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation) on Microsoft Learn.

The tools for a person (`adr_accept`, `review_decide`, and `collection_run_azure` when a host is configured) take
`actorId` from the token's `oid` claim. You can leave `actorId` out; if you send one it must be the same object id,
or the call is refused. They also need a token a person signed in to get (it carries the scope `access_as_user`), so a
service or an agent that signs in as itself can read, ingest, propose and evaluate, but cannot accept or decide.
There is no list of allowed client applications and no role check on those model tools yet: any valid token for your
tenant and audience can call them. That is a decision for now (ADR 0004), so control who can obtain a token with
"Assignment required" in step 4 below.

### Settings

None of these is a secret: they are identifiers. Put them in the deployment's settings (Container Apps: the app's
environment variables). The shapes below use placeholder ids; use your own from step 2 of the next section.

| Setting | Required with `entra` | Example shape | Meaning |
| --- | --- | --- | --- |
| `CC_AUTH_MODE` | yes | `entra` | `off` (default) or `entra`. |
| `CC_ENTRA_TENANT_ID` | yes | `00000000-0000-0000-0000-000000000002` | Your directory (tenant) id. |
| `CC_ENTRA_AUDIENCE` | yes | `api://00000000-0000-0000-0000-000000000003 00000000-0000-0000-0000-000000000003` | Accepted `aud` values, space or comma separated: the Application ID URI and the client id of the API registration. Version 1.0 tokens carry the first, version 2.0 tokens the second, so list both. |
| `CC_ENTRA_HUMAN_SCOPE` | no | `access_as_user` | The scope a token needs to call a tool for a person. |
| `CC_ENTRA_CLOCK_SKEW_SECONDS` | no | `60` | Tolerance on `exp` and `nbf`; 0 to 300. |
| `CC_ENTRA_JWKS_CACHE_SECONDS` | no | `900` | How long signing keys are cached; 60 to 86400. |
| `CC_BIND_HOST` | no | `127.0.0.1` | The interface to listen on (an IP address). |

If `CC_AUTH_MODE=entra` is set without the tenant id or the audience, the appliance refuses to start and says which
setting is missing. If any `CC_ENTRA_*` setting is present while sign-in is `off`, it also refuses to start, so a
half-finished setup cannot look protected.

### What you do in Microsoft Entra, once

1. Open the [Microsoft Entra admin center](https://entra.microsoft.com), then Identity, Applications, App
   registrations, New registration.
2. Name: `HCW Cloud Crawler API`. Supported account types: "Accounts in this organizational directory only
   (single tenant)". Leave Redirect URI empty. Select Register. On the Overview page, copy the "Application (client)
   ID" and the "Directory (tenant) ID": these are the values for `CC_ENTRA_AUDIENCE` and `CC_ENTRA_TENANT_ID`.
3. Open Expose an API. Next to "Application ID URI" select Add and accept the suggested `api://<client id>` value.
   Select Add a scope: Scope name `access_as_user`; Who can consent "Admins and users"; Admin consent display name
   `Act as the signed-in user`; Admin consent description `Lets the website call Cloud Crawler as the signed-in
   user.`; State "Enabled". The audience setting should list both the `api://...` value and the client id.
4. Open Identity, Applications, Enterprise applications, select `HCW Cloud Crawler API`, Properties, set "Assignment
   required?" to Yes, and Save. Then Users and groups, Add user/group, and add only the people allowed to use the
   appliance. Without this, any user in your tenant can obtain a token for the API.
5. Put TLS in front of the appliance (Container Apps ingress does this) so tokens never travel over plain HTTP, and
   list its public host name in `CC_ALLOWED_HOSTS`.
6. Set the settings in the table above, redeploy, and confirm that `GET /api/health` shows `"auth": "entra"` and that
   `POST /mcp` without a token answers `401`.
7. Make the client (the website) request tokens for the scope `api://<client id>/access_as_user`.

Details: [register an application](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app),
[expose a web API](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-configure-app-expose-web-apis)
and [restrict an app to assigned users](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/assign-user-or-group-access-portal).
Not yet checked against a real tenant: see `VALIDATION.md`.

## Releasing the engine

The AddOn adopts the engine as the wheel attached to a GitHub Release of
this repository, pinned by URL and sha256 (ADR 0002; the AddOn's
`core-update.yml` opens the bump pull request). A release is one tag, and
**a `v*` tag can never be moved or deleted once it is pushed** (see "Branch
and tag protection"), so the checks below run before the tag is accepted and
there is a dry run that publishes nothing. Releases are listed at
[github.com/saulpatinojr/HCW-CloudCrawler_App/releases](https://github.com/saulpatinojr/HCW-CloudCrawler_App/releases);
the `v0.1.0` page appears there once the tag has been pushed and
`release.yml` has finished (until then no release exists).

What a tag does. `release.yml` checks, then creates the release with the notes
from the changelog section. `publish-core.yml` checks, builds the wheel and the
sdist, verifies the wheel with `scripts/verify-core-wheel.py` (the engine, no
cloud SDK, no HTTP client, no Azure endpoint, pydantic as its only
requirement), writes a CycloneDX SBOM (the engine's locked runtime
dependencies), attests provenance and the SBOM, verifies the attestations, then attaches
**three files** to the release. Nothing is published to PyPI unless the
repository variable `PYPI_ENABLED` is `true` (it is not set), and no container
image is published by any workflow.

The check that cannot be skipped is `scripts/check-release-version.py`. On
every pull request it fails when the engine's `pyproject.toml`, the appliance's
`pyproject.toml`, the two `__version__` constants and the two `uv.lock` entries
do not all name the same `X.Y.Z`. On a tag it also requires that the tag is
`v` plus that version, that `CHANGELOG.md` has a dated, non-empty `## [X.Y.Z]`
section and nothing left under `[Unreleased]`, that the tagged commit is on
`main`, and that the build produced exactly the wheel and the sdist for that
version. To release a new version, change all six places in one pull request
(`make lock` updates `uv.lock`).

### Release steps

1. **Check the changelog.** `CHANGELOG.md` has the `## [0.1.0] - 2026-10-25` section holding everything that ships, and
   nothing under `[Unreleased]`. If you tag on a different day, change the date in that heading in a pull request first
   (`release.yml` takes the release notes from that section, and refuses a tag while `[Unreleased]` has entries or the
   section has no date). Keep both `pyproject.toml` files, both `__version__` constants and `uv.lock` at the same version.
2. **Dry run on `main`** (publishes nothing, writes no tag or release). bash or
   PowerShell, with the GitHub CLI signed in:

   ```bash
   gh workflow run release.yml --repo saulpatinojr/HCW-CloudCrawler_App --ref main
   gh workflow run publish-core.yml --repo saulpatinojr/HCW-CloudCrawler_App --ref main -f attest=true
   ```

   Open the Actions tab and wait for both runs to turn green. The `release`
   run shows the release notes a tag would publish. The `publish-core` run
   shows the sha256 of the wheel, the sdist and the SBOM and keeps the three
   files in the artifact `cloud-crawler-core-release-files`. With `attest=true`
   it also creates and verifies the attestations; they are permanent entries
   in the public signing log, so use `-f attest=false` to skip them.
3. **Tag `main` and push the tag.** PowerShell:

   ```powershell
   git switch main; git pull origin main; git tag -a v0.1.0 -m "cloud-crawler-core 0.1.0"; git push origin v0.1.0
   ```

4. **Check the result.** Both runs for the tag are green, and
   [the release page](https://github.com/saulpatinojr/HCW-CloudCrawler_App/releases/tag/v0.1.0)
   lists three assets: `cloud_crawler_core-0.1.0-py3-none-any.whl`,
   `cloud_crawler_core-0.1.0.tar.gz` and `cloud-crawler-core.cdx.json`.
   Within six hours the AddOn's `core-update.yml` opens its bump pull request;
   `gh workflow run core-update.yml --repo saulpatinojr/HCW-CloudCrawler_AddOn`
   (bash or PowerShell) runs it at once. To check where a wheel came from:

   ```bash
   gh attestation verify cloud_crawler_core-0.1.0-py3-none-any.whl --repo saulpatinojr/HCW-CloudCrawler_App --source-ref refs/tags/v0.1.0
   ```

If a release goes wrong, the tag stays (it cannot be deleted) and the AddOn may
already have pinned the wheel's sha256, so do not replace files under the same
version. Delete the bad release and its assets on the release page, fix the
problem on `main`, and release the next version (`0.1.1`), which also needs all
six version places and the changelog section. If a run fails before the files
are attached, re-run it from the Actions tab (Re-run failed jobs). If it
fails after some files were attached, delete those assets by hand first,
because an upload never replaces a file.

## Repository layout

```text
packages/cloud-crawler-core/   the engine: models, normalise, detectors, drift, ledger, redaction, hashing
src/cloud_crawler_appliance/   the appliance application: edition guard, config, logging, Entra sign-in, MCP server, HTTP API,
                               and mcp_host/ (the client of Azure MCP Server: contract, stdio and recorded hosts, collection)
tests/                         unit, security, contract (Azure MCP 3.0.0 snapshot) and acceptance suites
samples/                       fictional Resource Graph exports, decisions and recorded Azure MCP results
                               (subscription 00000000-0000-0000-0000-000000000001)
infrastructure/docker/         the hardened Dockerfile and the pinned base image
scripts/                       the lockfile check, the release version guard and the release wheel verifier
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
- Logs are content-free: counts, durations, flags and hashed identifiers. A rejected token is logged as a status and
  a fixed reason word, never the token, a claim or an identifier.
- With Entra sign-in on, the actor of a human-only tool is the validated token's object id, never a typed value, and
  an app-only token cannot call those tools (ADR 0004).
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
