# Validation record

Re-run on 2026-10-24 from `main` at commit `fc542be` (the first record, dated 2026-10-21, described the first implementation slice and the wave-one
detectors). The dependency, lint, lockfile, test, contract and pip-audit rows below were run again at `fc542be`, after the dependency bumps of pull requests
25, 30 and 31 (`pydantic` 2.14.1, `httpx2` 2.16.0, `fastapi` 0.157.0). The other rows were last run at `fed357b`; the only changes since then are in tests,
workflows, documents and locked dependency versions, so the engine wheel, the tool catalogue and the acceptance scenarios were not re-run. The numbers
below are the outputs of the commands as run in this session on Python 3.14.6, uv 0.11.32 and Node.js 22.22.0, except in the rows and cells that say CI.

## Ran

| Check | Command | Result |
| --- | --- | --- |
| Dependency resolution | `uv sync --all-packages` | 70 packages resolved; `mcp==2.3.0`, `fastapi==0.157.0`, `pydantic==2.14.1`; no cloud SDK |
| Lint and format | `uv run ruff check . && uv run ruff format --check .` | All checks passed; 59 files formatted |
| Lockfile export | `bash scripts/check-lockfiles.sh` | `requirements.lock.txt` matches `uv.lock` (hash-pinned, 300 lines) |
| Unit, security, acceptance | `uv run pytest -q --cov=packages --cov=src --cov-fail-under=85` | 218 passed, 1 deselected (the `azmcp` contract test); coverage 96.25 percent |
| Azure MCP 3.0.0 contract | `uv run pytest tests/contract -q -m azmcp` | 1 passed in 7.35 s: `npx @azure/mcp@3.0.0` started over stdio, `serverInfo.version` `3.0.0`, twelve tools across the seven namespaces matched `tests/contract/snapshots/azmcp-3.0.0-tools.json`; every tool the design calls is read-only and non-destructive |
| Azure MCP build identity | `npx -y @azure/mcp@3.0.0 --version` | `3.0.0+6369a8a7a9822e804f4986f67619dfcd28fc815b` (the `release/azure/3.x` branch head, not the tagged commit `61715e6a`; recorded in ADR 0001) |
| Known vulnerabilities | `uv run pip-audit -r requirements.lock.txt --strict` | No known vulnerabilities found |
| Startup refusal | `tests/security/test_startup_refusal.py` | A fresh process with `AZURE_CLIENT_SECRET` set exits 3 with a scrubbed `startup_refused` line |
| Zone-redundancy acceptance | `tests/acceptance/test_acceptance_zone_redundancy.py` | Passes in-process and over streamable HTTP (protocol `2026-07-28`): two contradicted, three supported, eight not applicable; score 60.0, coverage 1.0; one contradiction-kind proposal; verdicts equal the golden file |
| Wave-one acceptance | `tests/acceptance/test_acceptance_wave_one.py` | Passes in-process and over streamable HTTP: six claims over thirteen resources give 32 supported, 7 contradicted, 0 unknown, 39 not applicable; score 77.0, coverage 1.0; seven contradictions, five proposals; verdicts equal the golden file, which was checked by hand against the sample estate before it was committed. The scenario then accepts the decision and decides one proposal as a person: the actor id never appears in any result |
| Tool catalogue | `tests/unit/test_tools.py` | Fourteen tools without a host, fifteen with one; `adr_accept`, `review_decide` and `collection_run_azure` are the `human` caller class; eight are read-only; `adr_create`'s schema allows `draft` and `proposed` only; every refusal carries its code |
| Azure observations acceptance | `tests/acceptance/test_acceptance_azure_mcp.py` | Passes in-process and over streamable HTTP with the recorded host: `collection_run_azure` ingests five results (seven rows) under one run; the `New` Advisor record is contradicted citing one evidence id, the `Dismissed` one is accepted risk, the retirement opens a retirement-kind proposal due 2027-03-31, the initiative assignment is supported; score 45.5, coverage 1.0 |
| Engine wheel | `uv build --package cloud-crawler-core --out-dir dist` then `uv run --no-project --with pydantic python scripts/verify-core-wheel.py 'dist/cloud_crawler_core-*.whl'` | `cloud_crawler_core-0.1.0-py3-none-any.whl` and the sdist built; the wheel verified: 22 files, the detector registry, the Azure MCP normaliser and the drift engine present, no cloud SDK or HTTP client import, no Azure endpoint, `Requires-Dist: pydantic<3,>=2.14` only |
| CI on `main` | `ci`, `security` and `CodeQL` workflows at `fc542be` (CI, not run in this session) | All three succeeded (runs 40101984078, 40101984071, 40101984196). In the `ci` run the `image` job built the appliance image and its step "Startup refusal, non-root and health" passed, as did `lint`, `test` and `contract` |
| Azure MCP host | `tests/unit/test_mcp_host.py` | The allow-list refuses other tools before any request; `AZURE_*` variables are not passed to the child except `AZURE_TOKEN_CREDENTIALS`; parameters are stored as hashes; a failed source is recorded by code and the run continues |

## Ran for Entra sign-in (ticket #8, ADR 0004)

Run on the branch `claude/sweet-einstein-4y648v` on 2026-10-24, Python 3.14.6, uv 0.11.32, Node.js 22.22.0, in a session with no Azure and no Entra
access. These rows are about this change only; the rows above were not re-run for it, apart from the full test suite, which includes them.

| Check | Command | Result |
| --- | --- | --- |
| Lint, format, lockfiles | `uv run ruff check . && uv run ruff format --check . && bash scripts/check-lockfiles.sh` | All checks passed; 62 files formatted; `requirements.lock.txt` matches `uv.lock` (PyJWT 2.15.1 was already locked through `mcp`, so only the "via" line and the direct requirement changed) |
| Full suite and coverage gate | `uv run pytest -q --cov=packages --cov=src --cov-report=term-missing` | 302 passed, 1 deselected (the `azmcp` contract test); coverage 97.91 percent against the 96 percent gate |
| Entra validation, no network | `tests/unit/test_entra_auth.py` (66 tests) | An RSA key is generated at test time and served as a local key set. Valid v2.0, v1.0, client-id-audience, list-audience and in-skew tokens pass. Refused with the same 401 body: expired, expired beyond the skew, `nbf` in the future, wrong audience, wrong issuer, another tenant's issuer, wrong `tid`, missing `tid`, `oid`, `exp`, `nbf` or `aud`, unknown, missing and non-text `kid`, a token signed by another key, `alg: none`, HS256 keyed with the public key, RS384, a tampered payload, a non-JWT, two `Authorization` headers, an over-long token. `/api/*`, `/mcp` (GET, POST, DELETE) and unknown paths answer 401 without a token; `/api/health` stays open and flat. Key set caching, refetch cooldown, rotation, outage (503) and the default HTTPS fetcher (https only, status, size cap, no redirect) are covered |
| The actor comes from the token | same file | A typed `actorId` naming someone else is refused by `adr_accept`, `review_decide` and `adr_create` over streamable HTTP with a real token, and nothing changes; with no typed id the recorded actor is the sha256 of the token's `oid`; a matching id in any letter case is accepted; an app-only token, a token without the scope and a token with `idtyp: app` get `forbidden` from the human-class tools but can call the model-class ones; the scope is a setting; with sign-in off the typed actor works as before |
| Logs carry no token | same file | Three rejected requests produce exactly three `request_error` lines with the status and the words `expired`, `signature`, `missing`; the token, its payload segment, the object ids, the tenant id, the audience and the key id appear nowhere in the output |
| Startup | `tests/unit/test_main_entry.py`, `tests/unit/test_entra_auth.py` | `CC_AUTH_MODE=entra` without a tenant or audience exits 3 with the setting named; `CC_ENTRA_*` with sign-in off exits 3; the server binds `127.0.0.1` by default and `0.0.0.0` only with `CC_BIND_HOST`, with one `warning` line when that is unauthenticated |
| Real process smoke test | `CC_AUTH_MODE=entra ... uv run python -m cloud_crawler_appliance`, then `curl` | `POST /mcp` without a token answered `401` with `www-authenticate: Bearer`; `GET /api/health` answered 200 with `"auth": "entra"` |
| Azure MCP 3.0.0 contract | `uv run pytest tests/contract -q -m azmcp` | 1 passed (the real server over `npx`, no Azure sign-in); the snapshot is unchanged |
| Known vulnerabilities | `uv run pip-audit -r requirements.lock.txt --strict` | No known vulnerabilities found |

## Did not run

| Check | Why | Where it runs |
| --- | --- | --- |
| Docker image build and the image-level refusal, non-root and health checks | No Docker daemon was started in this session. The Dockerfile now sets `CC_BIND_HOST=0.0.0.0` (ticket #8); that line is untested until CI builds the image | `ci.yml` job `image`, which passed on `main` at `fc542be` (run 40101984078) and must pass on the pull request |
| Entra sign-in against a real tenant | No Entra tenant and no network access to `login.microsoftonline.com` in the session; every token in the tests is minted locally and the key set is a local fixture | The owner's first deployment with `CC_AUTH_MODE=entra`: the README lists the app registration and the check (`/api/health` shows `"auth": "entra"`, `POST /mcp` without a token answers 401, then a real token from the website works) |
| Base image digest re-resolution | Needs a registry read (`docker buildx imagetools inspect`) | The `image` job pulls the pinned digest and builds on every change (passed on `main` at `fc542be`). The `[VERIFY]` marker in `infrastructure/docker/versions.env` is still there; ticket #12 tracks it. How the two files relate: the Dockerfile writes the digest out in full on each `FROM` line and does not read `versions.env`; nothing in CI or the tests compares them, so `versions.env` is documentation only today and the two must be changed together by hand (see `infrastructure/README.md`) |
| Container registry path for Azure MCP (`azure-sdk/azure-mcp` versus `azure-mcp`) | No registry read; not needed by this slice (no Azure MCP container yet) | ADR 0001 step 1, at the first derived-image build |
| Gitleaks, CodeQL, dependency review | GitHub-hosted | `security.yml`, `codeql.yml`, `dependency-review.yml`. `security` and CodeQL passed on `main` at `fc542be`; dependency review passed on pull request 23 |
| The release itself (`release.yml`, `publish-core.yml` attaching the wheel, provenance attestation) | Runs on a `v*` tag, which the owner pushes after the merge; the attach step needs the release the other workflow creates | The first tag `v0.1.0`. No tag or release exists yet (checked on 2026-10-24); ticket #7 tracks it |
| The stdio host against a live Azure MCP Server with a signed-in credential | No Azure credential in the authoring session; the contract test proves only `initialize` and `tools/list` | The owner's `make run-stdio` after `az login`; the integration job of the roadmap |
| The recorded results against a live capture | No Azure access; the recordings were written by hand to the 3.0.0 result records read from the `release/azure/3.x` source on 2026-10-21 (`RecommendationListResult`, `PolicyAssignmentListCommandResult`, `SubscriptionListCommandResult`, the Group `Result`), with fictional values | The first live run replaces them with captured results of the fictional lab estate |

## Known limitations of this slice

- Ten detectors (the wave-one set and the three Azure observation detectors) and fourteen tools (fifteen with a
  host); the ledger is in memory and not partitioned by tenant or session yet. The `cost-ceiling` detector and
  `cost_estimate_attach` are not in this slice.
- The Azure MCP host speaks stdio only. The HTTP transport to a hosted server under a managed identity or an
  on-behalf-of token (the Container Apps model of proposal section 10.2) is not implemented; `azureConnectivity`
  therefore reports `stdio-developer-credential` or `recorded`, never `managed-identity` or `obo`.
- The observation detectors ignore tag selectors (Advisor and policy rows carry no tags) and match the claim's
  `resourceTypes` against the recommendation's impacted type; a record whose rows all lie outside the decision's
  scope says nothing about it and the claim answers `unknown`. The caller class in `meta.caller` is declared here and enforced by the website's orchestrator, as
  the proposal says; this server checks only that a human-class call names an actor.
- The detectors read what a Resource Graph export carries, and the property names were taken from the Resource Graph
  schema on 2026-10-21 without a live query (no Azure access in the authoring session). A property an export omits
  (private endpoint connections on types where Resource Graph does not project them, `publicNetworkAccess` on older
  storage accounts) answers `unknown` with the property named, never a verdict.
- A single virtual machine row answers `unknown` for zone redundancy. The design's `instanceSet` claim parameter
  (VMs sharing a tag value form the set, supported when the set spans two or more zones) needs a set-level reader
  that this slice does not have; the reading says so.
- Resource Graph exports carry no diagnostic settings, locks or sub-resource encryption state; claims on those stay
  `unknown` until the App edition's collectors exist.
- `/api/health` reports `azureConnectivity: not-configured` unless `CC_AZMCP_MODE` names a host.
- Sign-in is **off by default**. With `CC_AUTH_MODE=off`, `/api` and `/mcp` accept requests without any sign-in and the
  human-only tools only require a non-empty `actorId`; that is for a trusted lab network only (the README says so, and
  the server now binds loopback unless `CC_BIND_HOST` is set; the container image sets `0.0.0.0`). Ticket #8 stays open
  until the owner has enabled and checked it in a real deployment.
- Entra sign-in (ADR 0004) is **not tested against a real Entra tenant**: the claims and issuer shapes follow Microsoft Learn
  (access tokens, claims validation, retrieved 2026-10-24) but were not observed on a live token. Specifically unverified: that
  v1.0 and v2.0 `iss` values are exactly the two forms accepted; which `aud` form a given app registration issues (the setting
  takes both); that `scp` and `idtyp` look as assumed for the website's delegated tokens; and that the key set URL answers as
  coded.
- Entra sign-in does not yet include: an allow-list of client applications (who can obtain a token is controlled in Entra by
  "Assignment required"); per-role authorisation inside the model-class tools (any valid token for the tenant and audience can
  read, ingest, propose and evaluate); sovereign clouds (the public authority `login.microsoftonline.com` and
  `sts.windows.net` are fixed in `security/entra.py`); revocation (a stolen token works until it expires, as with any access
  token); token binding or proof-of-possession; rate limiting of failed sign-ins. A person's delegated token proves consent,
  not attention: an on-behalf-of service holding a person's token acts as that person.
- The tool schemas of `adr_accept`, `review_decide` and `collection_run_azure` now mark `actorId` optional (additive; the
  engine is unchanged). With sign-in off an empty `actorId` is still refused.
- The in-memory ledger is shared by everyone who can sign in; it is not partitioned by tenant, user or session yet, so a
  second tenant must not share one appliance.
- The template's labels and Discussions step was skipped (`--skip-github`); whether it has been done since was not
  checked. Ticket #12 tracks the template leftovers.
