# 0003. Only the App edition and the website call Azure MCP; the AddOn never calls Azure

- **Status:** Accepted
- **Date:** 2026-10-21
- **Owners:** Workload owner and architecture owner
- **Issue:** none; recorded from the owner-approved proposal *Azure Architecture MCP Appliance on Azure MCP Server 3.0* (website repository, `docs/architecture/azure-architecture-mcp-appliance.md`, sections 8, 11 and 12); the AddOn records its side as its own ADR 0001

## Context

The design has exactly two callers of Azure MCP: this App edition, running in Azure beside its own Azure MCP container
under a managed identity or on-behalf-of authentication, and the website's Function App in the lab chat path, which
forwards a signed-in visitor's delegated token per request. The AddOn runs on the website's lab host, credential-free
by construction, and the strongest tested property the program has is that it cannot construct an Azure credential.

## Decision

1. This repository owns the Azure MCP host (the MCP client), the live collectors and every tool annotated
   `callsAzure: true`. None of them exists in the engine package.
2. Every tool in both editions declares `meta.callsAzure`. The AddOn's security suite reads the tool list over the
   protocol and fails if any tool says `true`; this repository keeps the metadata honest so that test means something.
3. The identity this edition accepts is a managed identity (hosting identity mode) or a delegated token forwarded per
   request (on-behalf-of mode). It refuses to start when `AZURE_CLIENT_SECRET`, `AZURE_CLIENT_CERTIFICATE_PATH`,
   `AZURE_CLIENT_CERTIFICATE_PASSWORD`, `AZURE_USERNAME` or `AZURE_PASSWORD` is present. No client-secret credential
   class exists in the tree.
4. Evidence produced by this edition's Azure MCP host carries provenance (`sourceType: azure-mcp`, tool name, server
   version, protocol version, hashed parameters, identity mode, hashed actor id) so the AddOn, the website and a
   reader of the report can tell an observation from an upload.

## Alternatives considered

| Alternative | Benefits | Drawbacks | Reason not selected |
| --- | --- | --- | --- |
| The AddOn relays the visitor's token to Azure MCP | One fewer hop | A bearer for Azure Resource Manager scopes on a credential-free VPS; Azure egress from the lab host; the AddOn would handle Entra tokens, which its boundary test forbids | Weakens the proven property |
| The browser calls Azure MCP directly and uploads results | The Function App stays out of Azure | Widens the SPA's scopes and the site's content security policy; no server-side allow-list of tools | Recorded as an option, not the design |

## Consequences

- The lab path's Azure observations are produced by the website, not by this repository; this repository's Azure MCP
  host serves the App edition's own runs and the enterprise package.
- A future "bring your own appliance" catalogue row on the site would register an App edition instance for a tenant's
  users under the pane and status contracts, without the AddOn ever gaining Azure access.

## Validation

`tests/unit/test_config_and_edition.py` and `tests/security/test_startup_refusal.py` prove the refusal; the
acceptance test asserts every tool's `callsAzure` is `false` in this slice; `.github/workflows/ci.yml` greps for
client-secret credential classes.

## Rollback or revisit trigger

Revisit only with a new ADR in both repositories and a change to the AddOn's boundary test, which the program's
working agreements say never to weaken.
