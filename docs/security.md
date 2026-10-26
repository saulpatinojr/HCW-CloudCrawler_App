# Security

This page says who can call the appliance today, what it refuses to do, and how to report a problem. It is written
for someone who has not met the project before.

> **Sign-in is off by default.** With the default settings nobody is asked who they are. Anyone who can reach the port can read the evidence and accept decisions as if they were a trusted person. Run the appliance only on a trusted lab network until you turn sign-in on. Nothing on this site describes the appliance as ready for production, and `GET /api/health` reports `"production": false`.

## Report a vulnerability

Use GitHub's private reporting: open
[Report a vulnerability](https://github.com/saulpatinojr/HCW-CloudCrawler_App/security/advisories/new) on the
repository's Security tab. Please do not put exploit details, credentials, tenant identifiers or personal data in a
public issue. This is a one-maintainer project, so no response time is promised. The full policy is in
[SECURITY.md](../.github/SECURITY.md).

## Who can call the appliance

| Setting | What happens |
| --- | --- |
| `CC_AUTH_MODE=off` (the default) | `/api` and `/mcp` answer without any sign-in. The tools meant for a person (`adr_accept`, `review_decide`) only require that a non-empty `actorId` is supplied, so a caller can claim to be anyone. |
| `CC_AUTH_MODE=entra` | Every route except `GET /api/health` needs a Microsoft Entra access token. A missing or invalid token gets `401`. The person's identity comes from the validated token, never from the request body. |

What sign-in with `entra` checks: the token's signature against your tenant's published signing keys (RS256 only), its
issuer, audience, expiry and not-before time, and that your tenant issued it. If the signing keys cannot be fetched the
answer is `503`, never a pass. The token and its claims are never logged. The design and the decisions behind it are in
[ADR 0004](adr/0004-entra-token-validation-on-api-and-mcp.md).

Three things make the default less exposed:

- The server listens on `127.0.0.1` (this machine only) unless `CC_BIND_HOST` says otherwise. With sign-in off it
  refuses to start on any other address unless `CC_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true` is set on purpose (lab
  only), and it then writes one `warning` line. The container image sets `CC_BIND_HOST=0.0.0.0` and never sets that
  opt-out, so the image starts only with `CC_AUTH_MODE=entra` (or with the opt-out added by the person running it).
- With `CC_AUTH_REQUIRED_ROLES` set (sign-in on), a valid token must also carry at least one of those app roles in its
  `roles` claim; otherwise the answer is `403` with a body that does not say which roles would have been enough.
- A request with the wrong `Host` header gets `421`, and a cross-origin request to `/mcp` gets `403`. These are useful
  protections but they are not sign-in.
- `GET /api/health` reports `"auth": "off"` or `"auth": "entra"`, so you can see which one is running.

Microsoft Learn explains the background: [access tokens](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens)
and [claims validation](https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation). The steps to
register the API in Entra are in the
[repository README](../README.md#signing-in-with-microsoft-entra). What
sign-in does not cover yet is on [Known limitations](known-limitations.md).

## What the appliance refuses to do

- **It holds no Azure secret.** It refuses to start when any of `AZURE_CLIENT_SECRET`,
  `AZURE_CLIENT_CERTIFICATE_PATH`, `AZURE_CLIENT_CERTIFICATE_PASSWORD`, `AZURE_USERNAME` or `AZURE_PASSWORD` is set.
  Identity is meant to be a managed identity or a person's delegated token forwarded per request, never a stored secret.
- **Its logs hold no content.** Log lines carry counts, durations, flags and hashed identifiers. A rejected token is
  logged as a status and a fixed reason word.
- **It redacts what it ingests.** Payloads are redacted when they arrive, and the raw payload's hash is taken before
  redaction so a change is still noticed.
- **Only read-only Azure calls are allowed.** The Azure MCP host has an allow-list of read-only tools, and a contract
  test checks it against the pinned 3.0.0 server's tool list.
- **The AddOn cannot reach Azure at all** ([ADR 0003](adr/0003-the-addon-never-calls-azure.md)).

## How the build is protected

- Every GitHub Action is pinned to a full commit identifier, and runners use a fixed label (`ubuntu-26.04`).
- The `main` branch is protected by a repository ruleset: changes arrive through a pull request, and the checks `lint`,
  `test`, `contract`, `pip-audit`, `secret-scan` and `image` must pass. A `v*` release tag cannot be moved or deleted
  once pushed.
- Dependencies are locked with hashes, audited with `pip-audit`, and reviewed by GitHub's dependency review. CodeQL and a
  secret scan run on every change.
- The container image runs as a non-root user, and a weekly Trivy scan fails on any fixable HIGH or CRITICAL finding.
  The few findings that have no fix yet are written down with a reason, an owner and an expiry date in an
  accepted-risk file, so they are decided and not forgotten.
- The release workflow is built to attach a software bill of materials (SBOM, the list of what is inside the engine) and
  signed provenance to each release, and to refuse to replace a published file. It has not yet run for a real release,
  so those protections are designed and tested but not yet proven on a live release.

## What has not been tested

The Entra sign-in was run once against a real Entra tenant, the owner's demo tenant, on 2026-10-26, and every expected
answer matched ([the result](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/8#issuecomment-6409098598)).
It has not been verified behind HTTPS on a public host name, with a token for a service, for a user who is not assigned,
with an expired token or one from another tenant, or across a signing-key rotation. Every token in the automated tests is
still made locally. [Known limitations](known-limitations.md) lists this and the rest.
