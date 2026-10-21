# 0002. The engine is seeded here and moves downstream to the AddOn unchanged

- **Status:** Accepted
- **Date:** 2026-10-21
- **Owners:** Workload owner and architecture owner
- **Issue:** none; recorded from the owner-approved proposal *Azure Architecture MCP Appliance on Azure MCP Server 3.0* (website repository, `docs/architecture/azure-architecture-mcp-appliance.md`, sections 7, 9 and 17) and the program's existing pattern (Cloud Assessor ADR 0001 and ADR 0028)

## Context

Cloud Crawler has two editions: this App edition (Azure MCP host, collectors, persistent ledger, enterprise
deployment) and the AddOn lab edition the website integrates with (uploads and handed-in evidence, in-memory, two-hour
expiry, no Azure). Both must produce the same verdict for the same evidence, or a lab result cannot be trusted to
predict an appliance result. The Cloud Assessor pair already proved the model: one engine package, seeded in one
repository, adopted by the other as a released artifact, with a workflow that opens the bump pull request.

## Decision

1. `packages/cloud-crawler-core` is the engine: pydantic models, canonical hashing, redaction, normalisers, the
   detector registry, the drift engine, the in-memory ledger and the report bundle. It depends on pydantic only: no
   HTTP client, no cloud SDK, no I/O beyond what a caller hands in.
2. It is **written and versioned here**. Releases of this repository (`v*` tags) publish the wheel; the AddOn adopts
   it unchanged through its `core-update.yml` bump pull request, pinned by version and hash.
3. Detector ids, evidence kinds and tool names are only ever added, never renamed. A model forbids unknown fields.
   Scoring follows the program rule: severity weights critical 4 / high 3 / medium 2 / low 1; unknown lowers
   coverage, never score.
4. Anything that needs a credential, a persistent store, a scheduler, a pipeline runner, elicitation or sampling
   lives in `src/cloud_crawler_appliance`, never in the engine, so the AddOn can adopt the engine without adopting any
   of it (proposal section 17.3, "never enters the AddOn").

## Alternatives considered

| Alternative | Benefits | Drawbacks | Reason not selected |
| --- | --- | --- | --- |
| Two engines, one per edition | Each can specialise | Verdicts diverge; every detector is written twice | Defeats the lab's purpose |
| A shared git submodule | No release step | Submodules are fragile in review and in Dependabot | The wheel-by-hash model already works in the program |
| Engine in the AddOn, adopted by the App | The lab ships first | The App is the proving ground; the AddOn must stay small | Reverses the lifecycle the owner set |

## Consequences

- Every engine change lands here first, with golden fixtures, and reaches the AddOn only through a release.
- The engine's public surface (module paths, model field names, tool schemas) is a compatibility contract; breaking
  it bumps the major version and the AddOn's bump pull request is marked "needs adaptation".
- The AddOn carries a copy of the redaction helpers until the first engine release, with a comment saying so.

## Validation

`packages/cloud-crawler-core/pyproject.toml` lists pydantic as the only dependency; the image build asserts no cloud
SDK is importable; `tests/security/test_no_secrets.py` and the CI grep refuse client-secret credential classes in the
tree. The first release (`v0.1.0`) is the first time the AddOn adopts the engine.

## Rollback or revisit trigger

Revisit if the AddOn needs engine behaviour the App does not (it should not: promotion runs App → AddOn), or if the
release cadence of the engine becomes the bottleneck for lab fixes.
