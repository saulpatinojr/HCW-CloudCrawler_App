# Validation record

What ran, with what result, and what did not run, for the first implementation slice (2026-10-21). The numbers below
are the outputs of the commands as run in the authoring session on Python 3.14.6, uv 0.11.32 and Node.js 22.22.0.

## Ran

| Check | Command | Result |
| --- | --- | --- |
| Dependency resolution | `uv sync --all-packages` | 70 packages resolved; `mcp==2.3.0`, `fastapi==0.143.3`, `pydantic==2.14.0`; no cloud SDK |
| Lint and format | `uv run ruff check . && uv run ruff format --check .` | All checks passed; 40 files formatted |
| Lockfile export | `bash scripts/check-lockfiles.sh` | `requirements.lock.txt` matches `uv.lock` (hash-pinned, 300 lines) |
| Unit, security, acceptance | `uv run pytest -q --cov=packages --cov=src --cov-fail-under=85` | 97 passed, 1 deselected (the `azmcp` contract test); coverage 97.55 percent |
| Azure MCP 3.0.0 contract | `uv run pytest tests/contract -q -m azmcp` | 1 passed in 7.8 s: `npx @azure/mcp@3.0.0` started over stdio, `serverInfo.version` `3.0.0`, twelve tools across the seven namespaces matched `tests/contract/snapshots/azmcp-3.0.0-tools.json`; every tool the design calls is read-only and non-destructive |
| Azure MCP build identity | `npx -y @azure/mcp@3.0.0 --version` | `3.0.0+6369a8a7a9822e804f4986f67619dfcd28fc815b` (the `release/azure/3.x` branch head, not the tagged commit `61715e6a`; recorded in ADR 0001) |
| Known vulnerabilities | `uv run pip-audit -r requirements.lock.txt --strict` | No known vulnerabilities found |
| Startup refusal | `tests/security/test_startup_refusal.py` | A fresh process with `AZURE_CLIENT_SECRET` set exits 3 with a scrubbed `startup_refused` line |
| Zone-redundancy acceptance | `tests/acceptance/test_acceptance_zone_redundancy.py` | Passes in-process and over streamable HTTP (protocol `2026-07-28`): two contradicted, three supported, six not applicable; score 60.0, coverage 1.0; one contradiction-kind proposal; verdicts equal the golden file |

## Did not run

| Check | Why | Where it runs |
| --- | --- | --- |
| Docker image build and the image-level refusal, non-root and health checks | No Docker daemon in the authoring session | `ci.yml` job `image` |
| Base image digest re-resolution | Needs a registry read (`docker buildx imagetools inspect`) | First image build; `infrastructure/docker/versions.env` carries `[VERIFY]` |
| Container registry path for Azure MCP (`azure-sdk/azure-mcp` versus `azure-mcp`) | No registry read; not needed by this slice (no Azure MCP container yet) | ADR 0001 step 1, at the first derived-image build |
| Gitleaks, CodeQL, dependency review | GitHub-hosted | `security.yml`, `codeql.yml`, `dependency-review.yml` |
| Anything against Azure | This slice makes no Azure call by design | Week 3 of the roadmap (Azure MCP host over stdio with recorded results) |

## Known limitations of this slice

- One detector (`zone-redundancy`) and three tools (`adr_create`, `evidence_ingest`, `drift_evaluate`); the ledger is
  in memory and not partitioned by tenant or session yet.
- A single virtual machine row answers `unknown` for zone redundancy. The design's `instanceSet` claim parameter
  (VMs sharing a tag value form the set, supported when the set spans two or more zones) needs a set-level reader
  that this slice does not have; the reading says so.
- Resource Graph exports carry no diagnostic settings, locks or sub-resource encryption state; claims on those stay
  `unknown` until the App edition's collectors exist.
- `/api/health` reports `azureConnectivity: not-configured` because no Azure MCP host is wired yet.
- The template's labels and Discussions step was skipped (`--skip-github`); the owner runs it once from a signed-in
  `gh` (see the template's `docs/TEMPLATE.md` history in the first commit).
