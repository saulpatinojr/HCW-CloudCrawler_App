# 0001. Azure MCP Server is pinned to 3.0.0 and consumed as a separate process

- **Status:** Accepted
- **Date:** 2026-10-21
- **Owners:** Workload owner and architecture owner
- **Issue:** none; recorded from the owner-approved proposal *Azure Architecture MCP Appliance on Azure MCP Server 3.0* (website repository, `docs/architecture/azure-architecture-mcp-appliance.md`, sections 5 and 6)

## Context

Cloud Crawler treats Azure MCP Server as the source of truth for Azure observations. Upstream ships twice a week; the
3.0 cycle ran fifty betas over six months and `main` was already at `4.0.0-beta.2` on 2026-10-20, eight days after
3.0.0 went GA. A contract that moves twice a week cannot be the thing a deterministic engine is tested against. The
owner's brief asked for 3.0 as the baseline and said not to substitute a newer major silently.

Facts verified on 2026-10-21 against `microsoft/mcp`: the GA tag is `Azure.Mcp.Server-3.0.0`; the release branch is
`release/azure/3.x`; npm `@azure/mcp@3.0.0` reports `3.0.0+6369a8a7a9822e804f4986f67619dfcd28fc815b`, the branch
head, so the package was built from the branch rather than from the tagged commit; the README names the container
`mcr.microsoft.com/azure-sdk/azure-mcp` while the 3.0.0 changelog prints `mcr.microsoft.com/azure-mcp`.

## Decision

1. The pin is **3.0.0**: npm `@azure/mcp@3.0.0` for development and the contract test; the container
   `mcr.microsoft.com/azure-sdk/azure-mcp:3.0.0` resolved to a digest at the first image build (both registry paths
   are checked with `docker manifest inspect` and the one that resolves is recorded in `infrastructure/docker/versions.env`).
2. Azure MCP is consumed as a **separate process**: stdio in development, HTTP from the container in Azure. It is
   never linked, vendored or forked.
3. `tests/contract/snapshots/azmcp-3.0.0-tools.json` is the contract. The contract test starts the real server over
   stdio with the design's namespaces and compares names, input schemas, output schemas and annotations. It sends
   `initialize` and `tools/list` only; no Azure sign-in and no Azure call.
4. The snapshot is regenerated only with `CC_UPDATE_SNAPSHOT=1`, locally, in a pull request whose description says
   what changed and why. CI refuses to regenerate it.
5. An upgrade to a later major needs its own ADR that records: the tool-list diff reviewed, the on-behalf-of flow
   re-validated against the new release, every golden fixture regenerated, and the changelog entries between the two
   versions read for breaking changes.

## Alternatives considered

| Alternative | Benefits | Drawbacks | Reason not selected |
| --- | --- | --- | --- |
| Track `latest` | Newest tools and fixes without effort | Contract moves twice a week; golden tests and the OBO configuration can break without a change in this repository | Non-deterministic by construction |
| Pin 4.0.0-beta | Advisor service-group scope, `optimization` without a subscription | Beta; breaking changes still landing; the owner asked for 3.0 | Not the baseline the owner set |
| Embed the server as a library | One process | .NET AOT binary with its own cadence; no supported library surface | Not an option upstream offers |

## Consequences

- Development and CI need Node.js 22 for `npx @azure/mcp@3.0.0`; the npm wrapper downloads a platform package into its
  own cache (upstream fixed the lockfile side effect in 3.0.0-beta.46).
- 4.x features the roadmap would want (Advisor prioritisation, service groups) wait for the upgrade ADR.
- Security backports to the 3.x branch do not change the npm version; the pin is revisited when a backport that
  matters lands only in 4.x.

## Validation

`uv run pytest tests/contract -q -m azmcp` passes against the committed snapshot: server version `3.0.0`, twelve
read-only tools across `advisor`, `pricing`, `policy`, `group`, `subscription`, `wellarchitectedframework` and
`cloudarchitect`, with every tool the design calls annotated read-only and non-destructive (so no elicitation is
required). Recorded in `VALIDATION.md`.

## Rollback or revisit trigger

Revisit on the 4.0.0 GA tag, on a security advisory that is fixed only in 4.x, or when a needed tool exists only in a
later major. Rollback is not applicable: there is no earlier pin.
