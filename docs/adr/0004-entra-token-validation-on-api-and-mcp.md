# 0004. Validate Microsoft Entra access tokens on /api and /mcp, and take the actor from the token

- **Status:** Accepted
- **Date:** 2026-10-24
- **Owners:** Hybrid Cloud Works owner (saulpatinojr)
- **Issue:** [#8](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/8)

## Context

Until this decision the appliance answered every `/api` and `/mcp` request without asking who was calling, and it
listened on all network interfaces. The tools meant for a person (`adr_accept`, `review_decide`, and
`collection_run_azure` when a host is configured) were "human" only in their metadata: the server checked that
`actorId` was not empty, so anyone who could reach the port could say they were a human and accept a decision or
decide a review. That is acceptable on a developer's laptop and not on any shared network. `CLAUDE.md` also says the
server's identity is a managed identity or a delegated token forwarded per request, never a secret, so a design that
needed a stored shared key would pull the other way.

The owner chose the Microsoft Entra option on 2026-10-24: validate Entra access tokens on every route except health,
and take `actorId` from the token.

## Decision

1. **A setting turns it on.** `CC_AUTH_MODE` is `off` (the default, the lab behaviour) or `entra`. With `entra`,
   `CC_ENTRA_TENANT_ID` and `CC_ENTRA_AUDIENCE` are required and the appliance refuses to start without them. With
   `off`, any `CC_ENTRA_*` variable is refused at startup, so a half-finished setup cannot look protected.
2. **What is validated, on every route except `GET /api/health`** (a pure ASGI middleware in the host, in
   `src/cloud_crawler_appliance/security/entra.py`; the engine is untouched):
   - a single `Authorization: Bearer` header holding a JWT;
   - header `alg` is exactly `RS256` (so `none`, `HS*` and the other RSA variants are refused before any key is
     looked at), and `kid` must name a key in the tenant's published key set (JWKS); a `jku`, `jwk` or `x5u` header
     is never followed;
   - signature, then `iss` equal to the tenant's v2.0 or v1.0 issuer, `aud` equal to one of `CC_ENTRA_AUDIENCE`,
     `exp` and `nbf` present and valid with a clock skew of `CC_ENTRA_CLOCK_SKEW_SECONDS` (default 60, at most 300),
     `tid` equal to `CC_ENTRA_TENANT_ID`, and an `oid`;
   - any failure answers `401` with `WWW-Authenticate: Bearer` and the repository's error shape. A missing token
     says `unauthenticated`; every other failure says the same `invalid_token`, so the response does not tell an
     attacker which check failed. The one exception is a key set that cannot be fetched: `503 auth_unavailable` with
     `Retry-After`, because the server, not the token, is at fault. Both fail closed.
3. **The key set** is fetched from `https://login.microsoftonline.com/<tenant>/discovery/v2.0/keys` over HTTPS only,
   with a 5 second timeout, a 1 MiB cap and no redirects. It is cached for `CC_ENTRA_JWKS_CACHE_SECONDS` (default
   900). An unknown `kid` may trigger a refetch at most every 30 seconds, so invented key ids cannot turn into a
   download flood. Cached keys survive a short outage and are dropped after four cache lifetimes without a refresh.
   The fetcher is injectable, so tests use a local key and no network.
4. **The actor is the token's `oid`.** The tools store the sha256 of it, as before. `actorId` becomes optional in the
   tool schemas. When it is given it must equal the token's `oid` (compared without regard to letter case); a
   different value is refused with `forbidden` and nothing is changed. `adr_create` records the token as the author
   the same way. With `off`, the caller's `actorId` is used exactly as before.
5. **Who counts as a human.** A human-class tool needs a *person's delegated token*: it must carry the scope named
   by `CC_ENTRA_HUMAN_SCOPE` (default `access_as_user`) in `scp`, and must not be an app-only token (no `scp`, or
   `idtyp` of `app`). A service or an agent that signs in with its own application identity (client credentials)
   therefore gets `forbidden` from the human-class tools, and can still call the model-class tools (read, ingest,
   propose, evaluate). A service acting on a person's behalf (the on-behalf-of flow) carries that person's delegated
   token and is treated as that person: Entra proves the person consented, not that they were looking at the screen.
6. **Nothing is stored or forwarded.** The token is read, checked and dropped; only the validated `Principal`
   (object id, tenant id, scopes, app-only flag) lives for the request. No user token is stored, no secret-based
   credential is added, and the startup refusal of `AZURE_CLIENT_SECRET`, `AZURE_CLIENT_CERTIFICATE_PATH`,
   `AZURE_CLIENT_CERTIFICATE_PASSWORD`, `AZURE_USERNAME` and `AZURE_PASSWORD` is unchanged. Forwarding a user's token
   to Azure MCP through its on-behalf-of flow remains the planned HTTP-transport work; this decision only makes the
   caller's identity known.
7. **Logs.** A refusal logs `request_error`, the status and a fixed reason word (`expired`, `audience`, ...) through
   the content-free writer. No token, claim, object id or tenant id is logged.
8. **Exposure.** The default stays `off`, so the README's lab-only warning stays as an interim note. The server now
   binds `127.0.0.1` unless `CC_BIND_HOST` says otherwise; the container image sets `CC_BIND_HOST=0.0.0.0`, so the
   image behaves as before. Starting unauthenticated on a non-loopback address logs one `warning` line. Nothing is
   more exposed than before.

## Alternatives considered

| Alternative | Benefits | Drawbacks | Reason not selected |
| --- | --- | --- | --- |
| Lab only: keep no sign-in and rely on the README warning and the trusted network | No code, no new dependency, nothing to configure | Anyone who reaches the port can read evidence and accept decisions as a "human"; does not match `CLAUDE.md`'s identity rule; the ticket stays open | Not acceptable for any shared deployment. It remains the default **mode** (`off`) for the lab, not the design. |
| Both modes at once, chosen per deployment (Entra available, `off` as the lab default) | The lab and the laptop keep working with no tenant; the enterprise deployment is protected | One more setting to get right; an operator can forget to turn it on | **Selected**, with guards: Entra settings with sign-in off are refused, `/api/health` reports `auth`, and an exposed unauthenticated start logs a warning. |
| A shared API key or static bearer secret | Simple to implement | A secret to store, rotate and leak; no identity per person, so the human gate would still be a typed name; contradicts the managed-identity direction | Rejected. |
| Authenticate at the ingress (Container Apps built-in authentication) and trust the forwarded identity headers | No token code in the app | The app would trust headers any in-network caller can forge unless the ingress is the only path; the tool-level human check (scope, app-only) is not available; behaviour differs between a laptop and the cloud | Rejected as the only control. It can still sit in front as defence in depth. |
| Validate tokens but keep taking `actorId` from the caller | Smallest change | A signed-in caller could still record someone else's id; the ticket's acceptance criterion says the id comes from the token | Rejected. |

## Consequences

- **Security:** with `entra`, an unauthenticated caller can reach only `/api/health`. A valid token for the tenant
  and audience is enough for the model-class tools; the human-class tools additionally need a person's delegated
  token. A typed `actorId` can no longer impersonate anyone.
- **Not covered by this decision, and recorded in `VALIDATION.md`:** it was not run against a real Entra tenant; there
  is no allow-list of client applications (who may obtain a token is controlled in Entra, by "Assignment required" on
  the enterprise application); there is no per-role authorisation inside the model-class tools; only the public
  cloud authority is supported; revoked tokens stay valid until they expire (the usual access-token behaviour); the
  ledger is still in memory and not partitioned by tenant.
- **Compatibility:** `actorId` is optional in `adr_accept`, `review_decide` and `collection_run_azure`; existing
  callers that send it keep working with sign-in off, and with sign-in on must send a matching value or none. The
  engine package, its models and its detector ids do not change, so the AddOn is not affected by the code.
- **Operations:** a deployment must terminate TLS in front of the appliance (a bearer token over plain HTTP can be
  read on the wire), register an API in Entra, and set the settings below. One new direct dependency, PyJWT 2.15.1
  with its crypto extra (already locked through the `mcp` SDK), is pinned in the appliance's `pyproject.toml` only.
- **Performance:** one signature check per request on a worker thread; key set fetches are rare.

## Validation

- Implementation owner: the App edition host (`src/cloud_crawler_appliance`).
- Acceptance: `tests/unit/test_entra_auth.py` (no network, key generated at test time) proves that valid tokens pass
  and that missing, malformed, expired, not-yet-valid, wrong-audience, wrong-issuer, wrong-tenant, unknown-key,
  `alg: none`, HS256-with-the-public-key, wrong-signer and tampered tokens are refused, that `/api` and `/mcp` both
  answer 401 without a token while `/api/health` stays open and flat, that a typed `actorId` cannot override the
  token, that an app-only token cannot call a human-class tool, and that logs carry no token.
- Not covered: a run against a real tenant (see `VALIDATION.md`).

## What the owner must configure

1. Register an API application in Microsoft Entra (single tenant), expose an API with the delegated scope
   `access_as_user`, and set "Assignment required" on its enterprise application. The README lists every field.
2. Set `CC_AUTH_MODE=entra`, `CC_ENTRA_TENANT_ID` and `CC_ENTRA_AUDIENCE` (and, if wanted, `CC_ENTRA_HUMAN_SCOPE`)
   in the deployment's settings. These are identifiers, not secrets.
3. Put TLS in front of the appliance and list its public host name in `CC_ALLOWED_HOSTS`.
4. Make the caller (the website or another client) request tokens for the scope
   `api://<application client id>/access_as_user`.

## Rollback or revisit trigger

Set `CC_AUTH_MODE=off` (and remove the `CC_ENTRA_*` settings) to return to the lab behaviour; no data changes. Revisit
when: the managed-identity / on-behalf-of HTTP transport lands (the token validated here may become the assertion
that flow exchanges), a client-application allow-list or per-role authorisation is wanted, a sovereign cloud is
needed, or Entra changes the token claims this relies on (`oid`, `tid`, `scp`, `idtyp`).
