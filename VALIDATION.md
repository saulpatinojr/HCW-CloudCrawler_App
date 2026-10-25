# Validation record

Re-run on 2026-10-25 for the release-readiness change (branch `release/v0.1.0-readiness`), which sits on `main` at commit `ae2f271` (after the
Entra sign-in of pull request 34 and the `fastapi` 0.159.1 bump of pull request 36) and adds a release version guard, a dry run for the release
workflows and tests for both. Every row in "Ran" was run again in this session, except the rows that say CI. The numbers below are the outputs of the
commands as run on Python 3.14.6 (the repository's pin), uv 0.12.0 (and uv 0.11.32, the version the workflows install, for the wheel and SBOM rows),
Node.js 26.5.0 (CI uses 22) and Docker Desktop 29.9.2 on Windows. Earlier records are in the history of this file.

## Ran

| Check | Command | Result |
| --- | --- | --- |
| Dependency resolution | `uv sync --frozen --all-packages` | 70 packages resolved; `mcp==2.3.0`, `fastapi==0.159.1`, `pydantic==2.14.1`, `pyjwt==2.15.1`, `httpx2==2.16.0`; no cloud SDK |
| Lint and format | `uv run ruff check . && uv run ruff format --check .` | All checks passed; 65 files formatted |
| Lockfile export | `bash scripts/check-lockfiles.sh` | `requirements.lock.txt` matches `uv.lock` (hash-pinned) |
| Unit, security, acceptance | `uv run pytest -q --cov=packages --cov=src --cov-fail-under=96` | 362 passed, 1 deselected (the `azmcp` contract test); coverage 97.91 percent against the 96 percent gate. The base `main` has 302 tests; this change adds 60 (33 for the version guard, 27 for the workflow rules), which measure no product code, so the coverage figure is the same |
| Azure MCP 3.0.0 contract | `uv run pytest tests/contract -q -m azmcp` | 1 passed in 5.85 s: `npx @azure/mcp@3.0.0` started over stdio, `serverInfo.version` `3.0.0`, twelve tools across the seven namespaces matched `tests/contract/snapshots/azmcp-3.0.0-tools.json`; every tool the design calls is read-only and non-destructive |
| Azure MCP build identity | `npx -y @azure/mcp@3.0.0 --version` | `3.0.0+6369a8a7a9822e804f4986f67619dfcd28fc815b` (the `release/azure/3.x` branch head, not the tagged commit `61715e6a`; recorded in ADR 0001) |
| Known vulnerabilities | `uv run pip-audit -r requirements.lock.txt --strict` | No known vulnerabilities found |
| Startup refusal | `tests/security/test_startup_refusal.py` | A fresh process with `AZURE_CLIENT_SECRET` set exits 3 with a scrubbed `startup_refused` line |
| Zone-redundancy acceptance | `tests/acceptance/test_acceptance_zone_redundancy.py` | Passes in-process and over streamable HTTP (protocol `2026-07-28`): two contradicted, three supported, eight not applicable; score 60.0, coverage 1.0; one contradiction-kind proposal; verdicts equal the golden file |
| Wave-one acceptance | `tests/acceptance/test_acceptance_wave_one.py` | Passes in-process and over streamable HTTP: six claims over thirteen resources give 32 supported, 7 contradicted, 0 unknown, 39 not applicable; score 77.0, coverage 1.0; seven contradictions, five proposals; verdicts equal the golden file, which was checked by hand against the sample estate before it was committed. The scenario then accepts the decision and decides one proposal as a person: the actor id never appears in any result |
| Tool catalogue | `tests/unit/test_tools.py` | Fourteen tools without a host, fifteen with one; `adr_accept`, `review_decide` and `collection_run_azure` are the `human` caller class; eight are read-only; `adr_create`'s schema allows `draft` and `proposed` only; every refusal carries its code |
| Azure observations acceptance | `tests/acceptance/test_acceptance_azure_mcp.py` | Passes in-process and over streamable HTTP with the recorded host: `collection_run_azure` ingests five results (seven rows) under one run; the `New` Advisor record is contradicted citing one evidence id, the `Dismissed` one is accepted risk, the retirement opens a retirement-kind proposal due 2027-03-31, the initiative assignment is supported; score 45.5, coverage 1.0 |
| Engine wheel | `uv build --no-create-gitignore --package cloud-crawler-core --out-dir dist` then `python -I scripts/verify-core-wheel.py 'dist/cloud_crawler_core-*.whl'` (uv 0.11.32, the version `publish-core.yml` installs; the verifier imports only the standard library, so the old `--with pydantic` download is gone) | `cloud_crawler_core-0.1.0-py3-none-any.whl` and the sdist built; the wheel verified: 22 files, the detector registry, the Azure MCP normaliser and the drift engine present, no cloud SDK or HTTP client import, no Azure endpoint, `Requires-Dist: pydantic<3,>=2.14` only |
| CI on `main` | `ci`, `security` and `CodeQL` workflows at `ae2f271` (CI, not run in this session) | All three succeeded: [ci 40193083107](https://github.com/saulpatinojr/HCW-CloudCrawler_App/actions/runs/40193083107), [security 40193083125](https://github.com/saulpatinojr/HCW-CloudCrawler_App/actions/runs/40193083125), [CodeQL 40193083174](https://github.com/saulpatinojr/HCW-CloudCrawler_App/actions/runs/40193083174). In the `ci` run the `image` job built the appliance image and its step "Startup refusal, non-root and health" passed, as did `lint`, `test` and `contract` |
| Appliance image, locally | `docker build -f infrastructure/docker/Dockerfile -t hcw-cloud-crawler-appliance:release-readiness .` then the four checks of the `ci.yml` `image` job against that tag (Docker Desktop, context `desktop-linux`; the task image was removed afterwards) | Built (229,604,113 bytes). With `AZURE_CLIENT_SECRET=x` the container printed `startup_refused` and exited 3; `python -m pip` is absent; `id -u` is 10001 and the image user is `10001:10001`; with the port published on 127.0.0.1 only, `GET /api/health` answered 200 with `"edition":"appliance"`, `"auth":"off"`, version 0.1.0 and the ten detectors, and the container log carried the one `warning` line (`auth: false, exposed: true`) of the unauthenticated start on `0.0.0.0`. So the image binds all interfaces by its own `CC_BIND_HOST=0.0.0.0`, as decided |
| SBOM | `uv export --frozen --quiet --package cloud-crawler-core --no-dev --format cyclonedx1.5 -o sbom/cloud-crawler-core.cdx.json` (uv 0.11.32) | 2,281 bytes, CycloneDX 1.5, five components: `pydantic` 2.14.1, `pydantic-core` 2.50.1, `annotated-types`, `typing-extensions`, `typing-inspection`. Generated here; the attestation of it is not (see "Did not run") |
| Release version guard | `uv run python scripts/check-release-version.py`; `tests/unit/test_release_guard.py` | Prints `release version consistent: 0.1.0`: both `pyproject.toml` files, both `__version__` constants and both `uv.lock` entries agree. The 33 tests prove that each single disagreeing file, a non-`X.Y.Z` version, a wrong or malformed tag, a missing, undated or empty changelog section, entries left under `[Unreleased]`, a stray or wrong-version file in `dist/`, a wheel whose own version differs from its name, and a tagged commit that is not on the branch each fail with one clear line |
| Workflow rules | `tests/unit/test_workflows.py` | 27 tests pin the eight workflow files: every `uses:` is a full SHA with a version comment, every runner is `ubuntu-26.04`, top-level permissions are `contents: read`, no `--clobber`, nothing is published without a `v*` tag, the write permission sits only in the release-creating job, the guard runs in `ci.yml`, `release.yml` and `publish-core.yml`, and the coverage gate named in `ci.yml` is the one in `pyproject.toml` |
| Workflow syntax | `actionlint -shellcheck= -pyflakes= <file>` per file, then once with shellcheck on `release.yml` and `publish-core.yml`; `yamllint -c .yamllint.yaml` on both | No findings other than the known `ubuntu-26.04` label message (actionlint does not know it). Syntax only: this does not run the workflows |
| Action pins | `gh api repos/<owner>/<repo>/git/ref/tags/<tag>` (annotated tags dereferenced) and `.../releases/latest` for every `uses:` in `.github/` | Every pinned SHA is the commit its version comment names. Each is also the newest stable release of its action (`actions/checkout` v7.0.1, `actions/setup-python` and `actions/setup-node` v7.1.0, `actions/upload-artifact` v7.0.2, `actions/attest` and `actions/attest-build-provenance` v4.2.2, `github/codeql-action` v4.39.1, others as commented). `checkout`, `setup-python` and `setup-node` carry the major `v7` in their comment, which Dependabot accepts |
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
| Entra sign-in against a real tenant | No Entra tenant and no network access to `login.microsoftonline.com` in the session; every token in the tests is minted locally and the key set is a local fixture | The owner's first deployment with `CC_AUTH_MODE=entra`: the README lists the app registration and the check (`/api/health` shows `"auth": "entra"`, `POST /mcp` without a token answers 401, then a real token from the website works) |
| Base image digest re-resolution | Needs a registry read (`docker buildx imagetools inspect`) | The `image` job pulls the pinned digest and builds on every change (passed on `main` at `ae2f271`, and the image was built locally in this session). The `[VERIFY]` marker in `infrastructure/docker/versions.env` is still there; ticket #12 tracks it. How the two files relate: the Dockerfile writes the digest out in full on each `FROM` line and does not read `versions.env`; nothing in CI or the tests compares them, so `versions.env` is documentation only today and the two must be changed together by hand (see `infrastructure/README.md`) |
| Container registry path for Azure MCP (`azure-sdk/azure-mcp` versus `azure-mcp`) | No registry read; not needed by this slice (no Azure MCP container yet) | ADR 0001 step 1, at the first derived-image build |
| Gitleaks, CodeQL, dependency review | GitHub-hosted | `security.yml`, `codeql.yml`, `dependency-review.yml`. `security` and CodeQL passed on `main` at `ae2f271`; dependency review passed on pull request 23 |
| The release itself: `release.yml` creating the release, `publish-core.yml` attaching the wheel, sdist and SBOM, the provenance and SBOM attestations, `gh attestation verify`, `uv publish` | The pipeline has never run, and nothing here can run a workflow that is not on `main`. What was checked: the files by `actionlint` and `yamllint`, the rules by `tests/unit/test_workflows.py`, the build, wheel check and SBOM by running the same commands here, and the version guard by its tests. Not checked: that GitHub accepts the attestation steps and their permissions (`id-token`, `attestations`), that `gh release create/upload` work with `GITHUB_TOKEN` against the tag ruleset, that `gh attestation verify` accepts the SBOM predicate type `https://cyclonedx.org/bom`, and that a tag created by the owner starts both workflows | First the dry run after this change is merged (`release.yml` and `publish-core.yml` started by hand on `main`: README, "Release steps", step 2), then the first tag `v0.1.0`. No tag or release exists yet (checked on 2026-10-25); ticket #7 tracks it |
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
- Sign-in is **off by default**, and that is decided (owner, 2026-10-25, ADR 0004 "Owner decisions"): the appliance does not refuse to start without it. With `CC_AUTH_MODE=off`, `/api` and `/mcp` accept requests without any sign-in and the
  human-only tools only require a non-empty `actorId`; that is for a trusted lab network only (the README says so, and
  the server binds loopback unless `CC_BIND_HOST` is set; the container image sets `0.0.0.0`, also decided, and starting unauthenticated on a non-loopback address logs one `warning` line). Ticket #8 stays open
  until the owner has enabled and checked it in a real deployment.
- Entra sign-in (ADR 0004) is **not tested against a real Entra tenant**: the claims and issuer shapes follow Microsoft Learn
  (access tokens, claims validation, retrieved 2026-10-24) but were not observed on a live token. Specifically unverified: that
  v1.0 and v2.0 `iss` values are exactly the two forms accepted; which `aud` form a given app registration issues (the setting
  takes both); that `scp` and `idtyp` look as assumed for the website's delegated tokens; and that the key set URL answers as
  coded. The `503` answer when the key set cannot be fetched is intended (owner decision, 2026-10-25), not a gap.
- Entra sign-in does not yet include: an allow-list of client applications (who can obtain a token is controlled in Entra by
  "Assignment required"); per-role authorisation inside the model-class tools (any valid token for the tenant and audience can
  read, ingest, propose and evaluate; the owner decided on 2026-10-25 that this is fine for now); sovereign clouds (the public authority `login.microsoftonline.com` and
  `sts.windows.net` are fixed in `security/entra.py`); revocation (a stolen token works until it expires, as with any access
  token); token binding or proof-of-possession; rate limiting of failed sign-ins. A person's delegated token proves consent,
  not attention: an on-behalf-of service holding a person's token acts as that person.
- The tool schemas of `adr_accept`, `review_decide` and `collection_run_azure` now mark `actorId` optional (additive; the
  engine is unchanged). With sign-in off an empty `actorId` is still refused.
- The in-memory ledger is shared by everyone who can sign in; it is not partitioned by tenant, user or session yet, so a
  second tenant must not share one appliance.
- The template's labels and Discussions step was skipped (`--skip-github`); whether it has been done since was not
  checked. Ticket #12 tracks the template leftovers.
