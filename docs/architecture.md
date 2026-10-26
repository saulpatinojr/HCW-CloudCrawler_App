# Architecture

This page shows how the parts fit and where each rule is kept. The reasons behind each choice are in the
[decision records](adr/README.md).

## The parts

```text
 callers (the website, an AI assistant, a script)
        |  HTTPS or loopback; Microsoft Entra token when sign-in is on
        v
 +--------------------------------------------------------------+
 | the appliance  (src/cloud_crawler_appliance)                 |
 |   /api/health   flat status document                         |
 |   /mcp          14 MCP tools (15 with an Azure host)         |
 |   sign-in       Entra token check, human-only tools          |
 |   Azure MCP host  off | recorded | stdio                     |
 +--------------------------------------------------------------+
        |  calls                                   |  stdio child process
        v                                          v
 +-----------------------------------+     +------------------------------+
 | the engine (packages/             |     | Azure MCP Server 3.0.0       |
 |  cloud-crawler-core)              |     | (separate process, read-only |
 |  models, hashing, redaction,      |     |  tools only)                 |
 |  detectors, drift, in-memory      |     +------------------------------+
 |  ledger, report bundle            |                  |
 +-----------------------------------+                  v
                                                     Azure
```

| Part | What it owns | Rules it keeps |
| --- | --- | --- |
| **Engine** | Evidence, decision, claim, drift, contradiction and review models; canonical hashing; payload redaction; the detectors; the drift engine; the ledger; the report bundle. | Depends on `pydantic` only: no HTTP client, no cloud SDK, no file or network access. Detector ids and evidence kinds are only added, never renamed. |
| **Appliance** | The settings, the startup guard, the content-free logging, Entra sign-in, the MCP server, `/api/health` and the Azure MCP host. | Refuses to start with a secret-bearing Azure variable set. Every tool returns structured content plus short text and declares `callsAzure`. |
| **Azure MCP Server** | What Azure reports. | Pinned to 3.0.0 and never forked or linked; the appliance starts it as a child process. |

## The Azure MCP host

The host is how the appliance reaches Azure MCP Server. It has three modes, set with `CC_AZMCP_MODE`:

| Mode | What happens | Used for |
| --- | --- | --- |
| `off` (default) | No Azure tool exists. | Using the ledger with evidence you hand in. |
| `recorded` | Replays the fictional JSON results in `samples/azure-mcp`. | Trying the product and the tests, with no Azure access. |
| `stdio` | Starts Azure MCP Server 3.0.0 through `npx` as a child process, using the developer's own sign-in. | Development. Every call is read-only. |

A read-only allow-list refuses any other tool before a request is sent, and a contract test checks the allow-list
against the real 3.0.0 tool list. Hosted Azure MCP under a managed identity or an on-behalf-of token is planned, not
built ([Known limitations](known-limitations.md)).

## How a check flows

1. A caller sends evidence (`evidence_ingest`) or asks for a collection (`collection_run_azure`). The engine redacts
   it, hashes the original, adds provenance and an expiry, and stores it in the ledger.
2. A person or an assistant writes a decision (`adr_create`) with claims. A person accepts it (`adr_accept`).
3. `drift_evaluate` runs each claim's detector over the live evidence and stores the verdicts.
4. A contradiction or a retirement notice opens a review proposal; a person decides it (`review_decide`).

## Editions and where the engine goes

The App edition is the upstream product. The AddOn edition adopts the engine as a wheel (a Python package file) from a
GitHub Release of this repository, pinned by address and checksum, and **never** calls Azure.

| Decision | Summary |
| --- | --- |
| [ADR 0001](adr/0001-pin-azure-mcp-server-3-0-0.md) | Azure MCP Server is pinned to 3.0.0 and consumed as a separate process. |
| [ADR 0002](adr/0002-engine-moves-downstream-unchanged.md) | The engine is seeded here and moves downstream to the AddOn unchanged. |
| [ADR 0003](adr/0003-the-addon-never-calls-azure.md) | Only the App edition and the website call Azure MCP; the AddOn never does. |
| [ADR 0004](adr/0004-entra-token-validation-on-api-and-mcp.md) | Validate Microsoft Entra access tokens on `/api` and `/mcp`, and take the actor from the token. |

## State

The ledger is held in memory. It is lost when the program stops and is shared by everyone who can call the appliance;
it is not separated by tenant, user or session. A persistent ledger is planned.
