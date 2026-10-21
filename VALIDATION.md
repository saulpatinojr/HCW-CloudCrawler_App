# Validation record

What ran, with what result, and what did not run, for the first implementation slice and the wave-one detectors (2026-10-21). The numbers below
are the outputs of the commands as run in the authoring session on Python 3.14.6, uv 0.11.32 and Node.js 22.22.0.

## Ran

| Check | Command | Result |
| --- | --- | --- |
| Dependency resolution | `uv sync --all-packages` | 70 packages resolved; `mcp==2.3.0`, `fastapi==0.143.3`, `pydantic==2.14.0`; no cloud SDK |
| Lint and format | `uv run ruff check . && uv run ruff format --check .` | All checks passed; 47 files formatted |
| Lockfile export | `bash scripts/check-lockfiles.sh` | `requirements.lock.txt` matches `uv.lock` (hash-pinned, 300 lines) |
| Unit, security, acceptance | `uv run pytest -q --cov=packages --cov=src --cov-fail-under=85` | 208 passed, 1 deselected (the `azmcp` contract test); coverage 96.5 percent |
| Azure MCP 3.0.0 contract | `uv run pytest tests/contract -q -m azmcp` | 1 passed in 7.8 s: `npx @azure/mcp@3.0.0` started over stdio, `serverInfo.version` `3.0.0`, twelve tools across the seven namespaces matched `tests/contract/snapshots/azmcp-3.0.0-tools.json`; every tool the design calls is read-only and non-destructive |
| Azure MCP build identity | `npx -y @azure/mcp@3.0.0 --version` | `3.0.0+6369a8a7a9822e804f4986f67619dfcd28fc815b` (the `release/azure/3.x` branch head, not the tagged commit `61715e6a`; recorded in ADR 0001) |
| Known vulnerabilities | `uv run pip-audit -r requirements.lock.txt --strict` | No known vulnerabilities found |
| Startup refusal | `tests/security/test_startup_refusal.py` | A fresh process with `AZURE_CLIENT_SECRET` set exits 3 with a scrubbed `startup_refused` line |
| Zone-redundancy acceptance | `tests/acceptance/test_acceptance_zone_redundancy.py` | Passes in-process and over streamable HTTP (protocol `2026-07-28`): two contradicted, three supported, eight not applicable; score 60.0, coverage 1.0; one contradiction-kind proposal; verdicts equal the golden file |
| Wave-one acceptance | `tests/acceptance/test_acceptance_wave_one.py` | Passes in-process and over streamable HTTP: six claims over thirteen resources give 32 supported, 7 contradicted, 0 unknown, 39 not applicable; score 77.0, coverage 1.0; seven contradictions, five proposals; verdicts equal the golden file, which was checked by hand against the sample estate before it was committed. The scenario then accepts the decision and decides one proposal as a person: the actor id never appears in any result |
| Tool catalogue | `tests/unit/test_tools.py` | Fourteen tools without a host, fifteen with one; `adr_accept`, `review_decide` and `collection_run_azure` are the `human` caller class; eight are read-only; `adr_create`'s schema allows `draft` and `proposed` only; every refusal carries its code |
| Azure observations acceptance | `tests/acceptance/test_acceptance_azure_mcp.py` | Passes in-process and over streamable HTTP with the recorded host: `collection_run_azure` ingests five results (seven rows) under one run; the `New` Advisor record is contradicted citing one evidence id, the `Dismissed` one is accepted risk, the retirement opens a retirement-kind proposal due 2027-03-31, the initiative assignment is supported; score 45.5, coverage 1.0 |
| Azure MCP host | `tests/unit/test_mcp_host.py` | The allow-list refuses other tools before any request; `AZURE_*` variables are not passed to the child except `AZURE_TOKEN_CREDENTIALS`; parameters are stored as hashes; a failed source is recorded by code and the run continues |

## Did not run

| Check | Why | Where it runs |
| --- | --- | --- |
| Docker image build and the image-level refusal, non-root and health checks | No Docker daemon in the authoring session | `ci.yml` job `image` |
| Base image digest re-resolution | Needs a registry read (`docker buildx imagetools inspect`) | First image build; `infrastructure/docker/versions.env` carries `[VERIFY]` |
| Container registry path for Azure MCP (`azure-sdk/azure-mcp` versus `azure-mcp`) | No registry read; not needed by this slice (no Azure MCP container yet) | ADR 0001 step 1, at the first derived-image build |
| Gitleaks, CodeQL, dependency review | GitHub-hosted | `security.yml`, `codeql.yml`, `dependency-review.yml` |
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
- The template's labels and Discussions step was skipped (`--skip-github`); the owner runs it once from a signed-in
  `gh` (see the template's `docs/TEMPLATE.md` history in the first commit).
