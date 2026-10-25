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
this repository, pinned by URL and sha256 (ADR 0002). A release is one tag, and
**a `v*` tag can never be moved or deleted once it is pushed** (see "Branch
and tag protection"). Releases are listed at
[github.com/saulpatinojr/HCW-CloudCrawler_App/releases](https://github.com/saulpatinojr/HCW-CloudCrawler_App/releases);
the `v0.1.0` page appears there only at the very end of a successful run (until then no release is visible to
the public).

**What the checks can and cannot do.** The checks below run on GitHub *after*
you push the tag. They stop a bad tag from being *published*; they cannot
un-push it, so a wrong tag stays for ever and the only way forward is the next
version (or, as a last resort, the recovery below). That is why the dry run (step 2) comes first: it runs the same
checks against `main` without a tag. It is a rehearsal, not a guarantee. It cannot reproduce:

- **A tag on an older commit.** The workflow that runs for a tag is the copy stored *in the tagged commit*. A tag on a
  commit from before these checks existed would run that older workflow, without them, and nothing inside a workflow can
  detect that about itself. Step 3 therefore checks, before the tag exists, that the commit is the tip of `main` and
  that a dry run with attestations was green on exactly that commit (`scripts/pre-tag-check.py`).
- **The tag event itself.** The dry run never runs the `release` or `pypi` jobs. Whether GitHub starts the workflow for
  the tag, whether the workflow's token may create, check and publish the release, and the attestation fields for a tag
  (the dry run checks the same flags against `refs/heads/main`) are first exercised by the real tag. If the `release` job
  fails, nothing is public (see "If a release goes wrong").
One more limit, of the check rather than of the dry run: it refuses a changelog date that is *in the future*, but a date
that is merely old (more than a week) only gives a warning, because the release page will show that date and fixing it is
up to you.

**What a tag does.** One workflow, `publish-core.yml`, starts only for a tag of the exact form
`vMAJOR.MINOR.PATCH` (so `vtest` or `v0.1.0-rc.1` start nothing; the format is also checked by the guard). It runs four jobs in a fixed
order, and the release becomes public only as the very last step of the third:

1. `build` (read-only): `scripts/check-release-version.py` checks the tag, the
   versions and the changelog (details below); the wheel and the sdist are built;
   `scripts/verify-core-wheel.py` verifies the wheel (the engine, no cloud SDK, no
   HTTP client, no Azure endpoint, pydantic as its only requirement); a CycloneDX
   SBOM (the engine's locked runtime dependencies), the release notes and a list of
   sha256 checksums are written. Everything is kept as one workflow artifact.
2. `attest` (may sign, cannot write to the repository): attests provenance and the
   SBOM for the wheel and the sdist, then verifies the attestations. A new attestation can take a
   while to become readable, so the check retries with growing pauses for up to about four minutes in total.
3. `release` (the only job that can write to the repository, tag runs only):
   re-checks the checksums, verifies the attestations again, creates the release as a
   **draft** (not visible to the public) with the three files, re-reads the draft by its id until all three files are
   `uploaded` (GitHub's states are `uploaded` and `open`; it waits up to about two minutes), checks that the draft
   holds exactly `cloud_crawler_core-0.1.0-py3-none-any.whl`,
   `cloud_crawler_core-0.1.0.tar.gz` and `cloud-crawler-core.cdx.json`, and only then
   makes it public. A failure before that last step leaves no public release.
4. `pypi` (tag runs only): nothing is published to PyPI unless the repository
   variable `PYPI_ENABLED` is `true` (it is not set). No container image is published
   by any workflow.

Two things about what is checked. First, GitHub may report a sha256 ("digest") for each uploaded file. When it does, the
job compares it with the attested file; when it reports none, the job prints a notice and does **not** call the file
checked against GitHub's record: its integrity then rests on the sha256 list (checked in every job) and on the
attestations. Second, the SBOM file `cloud-crawler-core.cdx.json` is not a subject of any attestation. The attestation
covers the wheel and the sdist, with the SBOM as the attested statement about them (predicate type
`https://cyclonedx.org/bom`); the file on the release is covered by the sha256 list. To compare the two by hand, run
`gh attestation verify <wheel> --repo saulpatinojr/HCW-CloudCrawler_App --predicate-type https://cyclonedx.org/bom --format json`
and look at `verificationResult.statement.predicate` (GitHub documents that structure; this comparison has not been run
here).

The attestation check names the exact workflow file, the exact tag and the exact
commit (`gh attestation verify ... --signer-workflow --source-ref --source-digest`).
Without those, an attestation made by an earlier dry run of the same bytes would also
pass.

**The check that cannot be skipped in a pull request** is
`scripts/check-release-version.py`. On every pull request it fails when the engine's
`pyproject.toml`, the appliance's `pyproject.toml`, the two `__version__` constants
and the two `uv.lock` entries do not all name the same `X.Y.Z`. For a tag, and for
the dry run (which takes the tag to be `v` plus that version), it also requires that
the tag is `v` plus that version; that `CHANGELOG.md` has exactly one
`## [X.Y.Z] - YYYY-MM-DD` section, with a date that exists and is not in the future
(one day of slack for time zones) and with real entries (not just headings, comments or
link definitions); that nothing is left under Unreleased (`## [Unreleased]`, in any
letter case, with or without brackets); that the tagged commit is on `main`; that the
build produced exactly the wheel and the sdist for that version; and, in the dry run
only, that the tag does not exist yet. To release a new version, change all six places
in one pull request (`make lock` updates `uv.lock`).

### Release steps

1. **Check the changelog, and the pull requests.** `CHANGELOG.md` has the `## [0.1.0] - 2026-10-25` section holding
   everything that ships, and nothing under `[Unreleased]`. If you tag on a different day, change the date in that heading
   in a pull request first (the notes come from that section; a tag is refused while `[Unreleased]` has entries or the
   section has no valid date, and a date more than a week old only gives a warning). Keep both `pyproject.toml` files,
   both `__version__` constants and `uv.lock` at the same version. Then merge or close every open pull request that
   changes `.github/workflows/`, and do not merge a new one between the dry run and the tag: GitHub does not let a
   token without workflow permission create or change a release whose target commit modifies `.github/workflows/`
   compared with the default branch ([GitHub documentation](https://docs.github.com/en/rest/releases/releases)), and it
   answers 404 or 403. The release job uses such a token.
2. **Dry run on `main`, with attestations. This step is required, not optional.** It publishes nothing, writes no tag and
   no release, and runs only on the `main` branch. bash or PowerShell, with the GitHub CLI signed in:

   ```bash
   gh workflow run publish-core.yml --repo saulpatinojr/HCW-CloudCrawler_App --ref main -f attest=true
   ```

   Open [the Actions page](https://github.com/saulpatinojr/HCW-CloudCrawler_App/actions/workflows/publish-core.yml)
   and wait until **both** `build` and `attest` are green on the commit you are going to tag. The summary shows the release
   notes a tag would publish and the sha256 of the wheel, the sdist and the SBOM; the three files are kept in the artifact
   `cloud-crawler-core-release-files`. The `attest` job is why this step is required: the attestation steps are the one
   part nothing else can rehearse, and if they fail on the real tag, that tag is lost for good. The price is two permanent
   entries in the public signing log that name `refs/heads/main`; they cannot be mistaken for a release, because the tag
   run only accepts attestations for `refs/tags/v0.1.0`. Without `-f attest=true` only `build` runs, which is a
   cheaper check of the changelog and the build but does not satisfy step 3. If the run is red, read the message, fix
   `main` in a pull request, and run this step again.
3. **Check, then tag the commit the dry run built.** Do not tag whatever `git pull` gives you. `main` may have moved since
   the dry run, and a tag on an older commit would run that commit's older workflow. PowerShell, from your clone of this
   repository:

   ```powershell
   git switch main
   git pull origin main
   $sha = git rev-parse origin/main
   uv run python scripts/pre-tag-check.py --sha $sha --tag v0.1.0
   ```

   (`git pull` only brings your copy up to date; what gets tagged is `$sha`.) The check prints `ok:` lines and ends with
   `safe to tag`, or prints `error:` lines and ends with `NOT safe to tag`. It fails unless `$sha` is a full commit id
   that is the tip of `origin/main` (or is identical to the tip in `.github` and `scripts`), unless a dry run on `main`
   was green for exactly that commit with `build` **and** `attest` successful, and unless the tag does not exist in your
   clone. If `main` has moved since the dry run, run step 2 again first. Only after `safe to tag`:

   ```powershell
   git tag -a v0.1.0 $sha -m "cloud-crawler-core 0.1.0"
   git push origin v0.1.0
   ```

4. **Check the result.** The run for the tag is green (all of `build`, `attest` and `release`), and
   [the release page](https://github.com/saulpatinojr/HCW-CloudCrawler_App/releases/tag/v0.1.0)
   lists three assets: `cloud_crawler_core-0.1.0-py3-none-any.whl`,
   `cloud_crawler_core-0.1.0.tar.gz` and `cloud-crawler-core.cdx.json`. To check where a wheel came from:

   ```bash
   gh attestation verify cloud_crawler_core-0.1.0-py3-none-any.whl --repo saulpatinojr/HCW-CloudCrawler_App --signer-workflow saulpatinojr/HCW-CloudCrawler_App/.github/workflows/publish-core.yml --source-ref refs/tags/v0.1.0
   ```

5. **Adopt it in the AddOn (first time only).** See the next section: the AddOn's `core-update.yml` does **not** pick up
   the first release by itself.

### Adopting 0.1.0 in the AddOn (first time)

The AddOn's
[`core-update.yml`](https://github.com/saulpatinojr/HCW-CloudCrawler_AddOn/blob/main/.github/workflows/core-update.yml)
runs every six hours and when started by hand, but it only *bumps* a pin that already exists. Today the AddOn's
`pyproject.toml` has no line carrying `# CORE_REF`, so the workflow ends with the notice "no CORE_REF in pyproject.toml:
the engine is not adopted yet; nothing to bump" and opens no pull request. The first pin is made by hand, once:

1. In a clone of `HCW-CloudCrawler_AddOn`, create a branch and add this line to the `dependencies` list in `pyproject.toml`
   (one line, with the comment at the end; the workflow reads it):

   ```text
   "cloud-crawler-core @ https://github.com/saulpatinojr/HCW-CloudCrawler_App/releases/download/v0.1.0/cloud_crawler_core-0.1.0-py3-none-any.whl",  # CORE_REF v0.1.0
   ```

2. Run `uv lock` (it records the wheel's sha256 in `uv.lock`), then `uv run ruff check .` and `uv run pytest -q`, commit
   `pyproject.toml` and `uv.lock`, and open a pull request.
3. Add this entry at the top of "What changed" in the AddOn's `docs/whats-new-upstream.md`, in the same pull request
   (change the date if you tagged on another day):

   ```markdown
   ### 2026-10-25: App release v0.1.0 (engine cloud-crawler-core 0.1.0), first adoption

   - The App published its first GitHub Release, `v0.1.0`: the engine wheel
     `cloud_crawler_core-0.1.0-py3-none-any.whl`, the sdist, and a CycloneDX SBOM `cloud-crawler-core.cdx.json`, with
     provenance and SBOM attestations for the wheel and the sdist (check with `gh attestation verify <file>
     --repo saulpatinojr/HCW-CloudCrawler_App --signer-workflow
     saulpatinojr/HCW-CloudCrawler_App/.github/workflows/publish-core.yml --source-ref refs/tags/v0.1.0`).
   - Reaches this repository? Yes, once, by hand: `pyproject.toml` now pins the wheel by URL with a `# CORE_REF v0.1.0`
     line and `uv.lock` records its sha256. `core-update.yml` had nothing to bump before this line existed; from now on it
     opens a pull request for each new App release within six hours.
   - The engine is unchanged by the release machinery; the release is made by one workflow, `publish-core.yml`.
   ```

4. After the pull request is merged, `gh workflow run core-update.yml --repo saulpatinojr/HCW-CloudCrawler_AddOn`
   (bash or PowerShell) should answer "already at v0.1.0". Later App releases then arrive as bump pull requests.

### If a release goes wrong

The tag stays (it cannot be deleted), so version `0.1.0` can only ever mean the commit it was pushed on.
**What "Re-run failed jobs" does:** it runs the workflow file *as it is in the tagged commit*, and it reuses
the files built by that run. A fix merged to `main` afterwards cannot reach it. So a re-run helps only when the failure
was temporary (a network error, a GitHub outage); it cannot fix a mistake in the workflow, the scripts or the changelog.

**If the `release` job fails, nothing is public.** The step's error lines (also in the run's summary) say what stopped it.
A *draft* release may be left behind on the
[Releases page](https://github.com/saulpatinojr/HCW-CloudCrawler_App/releases) (marked "Draft"; only people who can write
to the repository see it). To clean up: open the draft, choose "Delete this release" (the tag stays), then "Re-run failed
jobs" if the cause was temporary. The job refuses to touch a release that already exists and never replaces a file, so a
leftover draft makes a re-run stop with a message saying so.

| What happened | What the public sees | What to do |
| --- | --- | --- |
| `build` or `attest` failed | No release at all | If the cause was temporary, "Re-run failed jobs". Otherwise see "Publishing by hand" below if the artifact and the attestations exist, or fix `main` and ship `0.1.1` (all six version places and a changelog section). |
| `release` failed before its last step | No release. A draft may be listed, visible only to writers | Delete the draft (above). Then "Re-run failed jobs" if temporary; if GitHub refused with 403 or 404, see "Publishing by hand"; otherwise ship `0.1.1`. |
| `release` succeeded, `pypi` failed (only if `PYPI_ENABLED` is `true`) | The release is complete and public | Fix the PyPI side and "Re-run failed jobs" (only `pypi` runs). |
| A release went public with a wrong file | A wrong release | The AddOn may already have pinned the wheel's sha256, so never replace files under the same version. Delete the release and its assets, fix `main`, and ship `0.1.1`. |

**Publishing by hand, when the tag is burned but the built and attested files are fine.** Use this instead of shipping
`0.1.1` when `build` and `attest` were green on the tag run, the `release` job could not publish, and no release for the tag was ever
public. It creates the release for the same tag from the same files, with your own GitHub sign-in instead of the workflow's
token. The run's artifact is kept for 90 days. bash (Git Bash on Windows works), from a clone of this repository on `main`,
with the id of the tag run from `gh run list --repo saulpatinojr/HCW-CloudCrawler_App --workflow publish-core.yml --event push --limit 5`
(use the run for `v0.1.0`; call its id `RUN`):

```bash
gh run download RUN --repo saulpatinojr/HCW-CloudCrawler_App -n cloud-crawler-core-release-files -D release-files
(cd release-files && sha256sum --check --strict SHA256SUMS)
python scripts/release-publish.py verify-attestations --dir release-files/dist --repo saulpatinojr/HCW-CloudCrawler_App --workflow .github/workflows/publish-core.yml --source-ref refs/tags/v0.1.0 --source-digest "$(git rev-parse 'v0.1.0^{commit}')"
python scripts/release-publish.py publish --repo saulpatinojr/HCW-CloudCrawler_App --tag v0.1.0 --dir release-files
```

The last command is the same code the workflow runs: draft first, the three files checked, then public. If GitHub answers
with a message about workflows, run `gh auth refresh -s workflow` and try again. Nothing here changes the tag.

**Last resort: lifting the tag rule.** That a `v*` tag cannot be moved or deleted is a *repository rule* (the ruleset
"Protect release tags"), not a law of GitHub. The owner can lift it under
[Settings, Rules, Rulesets](https://github.com/saulpatinojr/HCW-CloudCrawler_App/settings/rules), and the
`repository-admin` task `protect-release-tags` re-applies it afterwards. **Decision recorded here: do not lift it.** The only
case that would justify it is a tag that points at the wrong commit, with no release for it ever public and nothing pinned to
it (then the tag could be deleted and created again on the right commit, and the rule restored at once). If any release for
the tag was ever public, ship the next version instead.

Immutable releases are currently off for this repository (checked on 2026-10-25 with
`gh api repos/saulpatinojr/HCW-CloudCrawler_App/immutable-releases`, which answered `enabled: false`). If you turn them on
([GitHub documentation](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)),
a published release can no longer be edited or have files added, and its tag is locked. The draft-then-publish order here
is the order GitHub recommends for that, so the pipeline keeps working; the only change is that a wrong public release then
can never be repaired in place, only superseded by `0.1.1`.

## Repository layout

```text
packages/cloud-crawler-core/   the engine: models, normalise, detectors, drift, ledger, redaction, hashing
src/cloud_crawler_appliance/   the appliance application: edition guard, config, logging, Entra sign-in, MCP server, HTTP API,
                               and mcp_host/ (the client of Azure MCP Server: contract, stdio and recorded hosts, collection)
tests/                         unit, security, contract (Azure MCP 3.0.0 snapshot) and acceptance suites
samples/                       fictional Resource Graph exports, decisions and recorded Azure MCP results
                               (subscription 00000000-0000-0000-0000-000000000001)
infrastructure/docker/         the hardened Dockerfile and the pinned base image
scripts/                       the lockfile check, the release version guard, the pre-tag check, the release publisher, the release wheel verifier, the image scan and the documentation site builder
.github/workflows/             ci, security, image-scan, codeql, dependency-review, pages (the documentation site), publish-core (the whole release), repository-admin
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
- **Protect release tags:** a `v*` tag cannot be moved or deleted once pushed. This is a repository rule that the owner
  could lift, not a law of GitHub (see "Last resort: lifting the tag rule" under "Releasing the engine"). Check the
  version before tagging.

## Image scan and accepted risk

The appliance image is built on a Debian base image, and Debian packages sometimes carry a known vulnerability that has no
fixed version yet. So that the same findings do not keep resurfacing without anyone deciding about them, the workflow
`.github/workflows/image-scan.yml` builds the image and scans it with Trivy every Monday at 05:37 UTC, on **Run workflow**,
and on a pull request that changes `infrastructure/docker/`, `requirements.lock.txt` or the scan files. It is not one of
the six required checks: a vulnerability published tomorrow must not block an unrelated pull request.

- **It fails** (red run) on a HIGH or CRITICAL vulnerability that has a fix available and that `.trivyignore.yaml` does
  not accept. The answer is to update the base image (see `infrastructure/README.md`).
- **It warns** about a HIGH or CRITICAL vulnerability that has no fix and is not in `.trivyignore.yaml`. The answer is a
  decision by the owner: add an entry, or act.
- **`.trivyignore.yaml` is the accepted-risk file.** Each entry has an id, a reason, an owner and an expiry date
  (at most 180 days ahead). When the date passes, Trivy stops hiding the finding and `tests/unit/test_image_scan.py` fails
  until someone reads the entry again, then renews or removes it. Its header records the first scan (2026-10-25): 164
  findings in the Debian packages, none with a fix; 44 of them HIGH, which are 8 distinct vulnerabilities, all accepted
  for now with a reason; none CRITICAL; nothing in the Python packages.

To run the scan yourself, with Docker running (on Windows, Docker Desktop with the `desktop-linux` context), in bash:

```bash
bash scripts/scan-image.sh
```

It builds the image, scans it in a disposable, locked-down container (read-only file system, no capabilities, no Docker
socket), prints a summary and removes everything it created. Trivy is pinned by digest (a tag alone can be moved; see
[GHSA-69fq-xp46-6x23](https://github.com/advisories/GHSA-69fq-xp46-6x23)). Docs:
[Trivy](https://trivy.dev/latest/docs/), [ignoring findings](https://trivy.dev/latest/docs/configuration/filtering/).

## The documentation site

The pages you are reading can also be published as a small website with GitHub Pages. The site is rendered from the
files in this repository (this README, `VALIDATION.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `.github/SECURITY.md` and
`docs/adr/`), so there is no second copy to keep up to date, and its menu points at sections of this page. To build it
yourself and check every link, in bash or PowerShell, from the repository root:

```bash
uv sync --locked --only-group docs
uv run --locked --only-group docs python scripts/build-pages.py
```

You should see `built 10 pages in _site; every internal link and fragment resolves`; open `_site/index.html` in a browser.
The workflow `.github/workflows/pages.yml` runs the same build on every pull request that changes those files. It publishes
only after the owner turns Pages on, which makes the rendered text public (the repository itself is already public):

1. Run `gh api -X POST repos/saulpatinojr/HCW-CloudCrawler_App/pages -f build_type=workflow` (or choose **GitHub Actions**
   as the source under [Settings, Pages](https://github.com/saulpatinojr/HCW-CloudCrawler_App/settings/pages)).
2. Run `gh variable set PAGES_ENABLED --body true --repo saulpatinojr/HCW-CloudCrawler_App`.
3. Under Actions, choose **pages**, **Run workflow**, branch `main`. The run's `deploy` job prints the site address.

Docs: [Using custom workflows with GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Repository standards

This repository carries `CONTRIBUTING.md` (how a change gets into `main`), `CODE_OF_CONDUCT.md`, `CHANGELOG.md`,
`.github/SECURITY.md`, `.github/CODEOWNERS`, the pull request template and the issue forms (bug report, feature request,
decision record, work item), CodeQL, dependency review, Dependabot, CodeRabbit and Qlty configuration, and `docs/adr/`.
Pull requests open ready for review and follow the pull request template in `.github/`; `CHANGELOG.md` is updated in the same
pull request as the change.

## Contributing, security, license

See `CONTRIBUTING.md`, `.github/SECURITY.md` and [LICENSE](LICENSE) (MIT).
