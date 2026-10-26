# 0004. Validate Microsoft Entra access tokens on /api and /mcp, and take the actor from the token

- **Status:** Accepted
- **Date:** 2026-10-24
- **Amended:** 2026-10-26 (refuse an unauthenticated non-loopback start; optional app-role check; see "Amendment of
  2026-10-26")
- **Updated:** 2026-10-26 (the real-tenant check was run once; no decision changed; see "Update of 2026-10-26" before
  "Rollback or revisit trigger")
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
8. **Exposure** (partly superseded by the amendment of 2026-10-26: the image no longer starts unauthenticated without
   an explicit opt-out). The default stays `off`, so the README's lab-only warning stays as an interim note. The server now
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
- **Not covered by this decision, and recorded in `VALIDATION.md`:** it was not run against a real Entra tenant (it has
  since been run once, see "Update of 2026-10-26"); there
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
- Not covered when this was written: a run against a real tenant (done since, see "Update of 2026-10-26" and
  `VALIDATION.md`).

## What the owner must configure

1. Register an API application in Microsoft Entra (single tenant), expose an API with the delegated scope
   `access_as_user`, and set "Assignment required" on its enterprise application. The README lists every field.
2. Set `CC_AUTH_MODE=entra`, `CC_ENTRA_TENANT_ID` and `CC_ENTRA_AUDIENCE` (and, if wanted, `CC_ENTRA_HUMAN_SCOPE`)
   in the deployment's settings. These are identifiers, not secrets.
3. Put TLS in front of the appliance and list its public host name in `CC_ALLOWED_HOSTS`.
4. Make the caller (the website or another client) request tokens for the scope
   `api://<application client id>/access_as_user`.

## Owner decisions

On 2026-10-25 the owner (saulpatinojr) answered "go ahead" to the recommendations written in
[pull request 34](https://github.com/saulpatinojr/HCW-CloudCrawler_App/pull/34), the pull request that implemented this
decision. Four open design questions are therefore settled. They are the intended behaviour, not gaps, and each one
names what would reopen it.

| # | Question | Decision | Where it lives | Reopen when |
| --- | --- | --- | --- | --- |
| 1 | What should the appliance answer when it cannot fetch the Entra signing keys? | Keep `503 auth_unavailable` with `Retry-After`. It fails closed, and it tells the caller the server, not the token, is at fault. It never answers `401` for this, and never lets the request through. | `security/entra.py`; Decision item 2 above | Callers need to tell an outage from a bad token in a different way |
| 2 | Should `CC_AUTH_MODE=off` stay the default? | Yes. Sign-in stays off unless the operator turns it on, so the lab and a laptop keep working with no tenant. Starting unauthenticated on a non-loopback address writes one `warning` line and `GET /api/health` reports `"auth": "off"`. The appliance does **not** refuse to start in that case. | `config.py` (`auth_mode = "off"`), `__main__.py`; Decision items 1 and 8 | A deployment target exists that is not a trusted lab network (then make `entra` the default for the image, or refuse to start unauthenticated on a non-loopback address) |
| 3 | Where should the server listen by default? | On `127.0.0.1` (this machine only). `0.0.0.0` is used only inside the container image, which sets `CC_BIND_HOST=0.0.0.0`, and wherever an operator sets `CC_BIND_HOST` on purpose. | `config.py` (`bind_host`), `infrastructure/docker/Dockerfile`; Decision item 8 | The image is deployed somewhere without a network boundary in front of it |
| 4 | Who may call the model tools (read, ingest, propose, evaluate)? | Any valid token for the configured tenant and audience. There is no client-application allow-list and no role check yet, which the owner called "fine for now". Who can obtain a token is controlled in Entra ("Assignment required" on the enterprise application). The person-only tools still need a person's delegated token (Decision item 5); that part is unchanged. | `security/entra.py`, `mcp_server.py`; Consequences above | A second client application, a service account with narrower rights, or per-role authorisation is wanted (see the revisit triggers below) |

Nothing in the code changed because of these answers: they confirm what pull request 34 already merged. Part of
rows 2, 3 and 4 was then superseded on 2026-10-26 (see the amendment at the end of this record). Ticket
[#8](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/8) was kept open then, because the real-tenant
check (`VALIDATION.md`) was still to do; it has been done since (see "Update of 2026-10-26").

## Amendment of 2026-10-26: refuse an unauthenticated non-loopback start, and an optional role check

On 2026-10-26 the owner (saulpatinojr) asked for the two hardening steps that the owner decisions above had deferred
("only when a deployment outside a lab exists"): a sandbox Entra tenant is now available and the owner asked whether
the appliance can be deployed, so both are built now, in
[ticket #8](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/8). This amendment supersedes the "does not
refuse to start" part of owner decision 2, the "the image behaves as before" part of Decision item 8, and the "no role
check yet" part of owner decision 4. Everything else in this ADR stands. The default `CC_AUTH_MODE=off` and the
loopback default for `CC_BIND_HOST` do not change.

1. **No unauthenticated start on a non-loopback address.** With `CC_AUTH_MODE=off`, `Settings` raises (so the process
   exits 3 with the setting named, before anything listens) when `CC_BIND_HOST` is not a loopback address
   (`127.0.0.0/8`, `::1`), unless `CC_ALLOW_UNAUTHENTICATED_NON_LOOPBACK` is `true`. Only a clear yes counts (`1`,
   `true`, `yes`, `on`); an empty or unrecognised value is not an opt-out. The opt-out is refused when
   `CC_AUTH_MODE=entra`, like the `CC_ENTRA_*` settings with sign-in off, so it cannot sit in a deployment's settings
   and become live after a later switch. Using it logs the existing one-line `warning` (`auth: false, exposed: true`).
2. **The image does not carry the opt-out.** The safest design that keeps lab use possible is: the image keeps
   `CC_BIND_HOST=0.0.0.0` (a container must listen on every interface to be reached through a published port) and sets
   neither `CC_AUTH_MODE` nor the opt-out. `docker run` with no settings therefore exits 3 with a message naming both
   ways out (turn sign-in on, or, lab only, add `-e CC_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true`). A deployment cannot
   end up open by leaving settings out. The `ci.yml` image job proves the refusal, then starts the image with the
   opt-out (health answers) and with placeholder Entra settings (`/api/health` says `entra`, a request without a token
   gets `401`); `tests/unit/test_auth_hardening.py` asserts the Dockerfile never sets the opt-out and that CI is the
   only workflow that uses it.
3. **Optional app-role check.** `CC_AUTH_REQUIRED_ROLES` is a comma or space separated list of app role values
   (default empty: no check, today's behaviour; refused with sign-in off). The role values are the `roles` claim that
   Entra puts in the token of a user who was assigned the role, or of an application that was granted it. After the
   token is valid, a request whose `roles` claim holds none of the listed values is answered `403` with
   `{"error": {"code": "forbidden", "message": "this identity is not allowed to use the service"}}`, no
   `WWW-Authenticate` header and no mention of which roles would have been enough; the log line is the status and the
   fixed word `role`. A `roles` claim that is not a list of text counts as no roles. The check covers every route
   except `GET /api/health`, runs after (never instead of) the token checks, so an invalid token is still `401`.
4. **Delegated tokens keep working exactly as item 5 above says.** The role check and the person check are separate
   gates. A person's delegated token (`scp` holds `access_as_user`, not app-only) that also carries a required role may
   call the person-only tools; an app-only token that carries the role may call the model tools but still gets
   `forbidden` from the person-only tools. A person who was not assigned the role gets `403` before any tool runs, so
   with roles required the app role must be assigned to the people (or a group) as well as "Assignment required".
5. **The role value must differ from the scope value.** Entra refuses an app registration whose app role and
   delegated scope share one value (the Cloud Assessor real-tenant run hit this). The README's app role and sandbox
   runbook use `CloudCrawler.Access` and `access_as_user`, and `tests/unit/test_runbook.py` fails if they ever match.

Consequences: a deployment that today relies on the image starting with no settings stops starting, on purpose; the
fix is one of the two settings above. The engine package, its models and its detector ids do not change, so the AddOn
is not affected by the code. The role check is one gate for the whole service, not a permission per tool; a client
application allow-list is still not built. When this amendment was written the runbook had not been run: the README's
"Checking sign-in against a real tenant" was the way to observe that the `roles` claim looks as assumed (`VALIDATION.md`).

## Update of 2026-10-26: the real-tenant check was run

Later on 2026-10-26 the README runbook "Checking sign-in against a real tenant" was run once, in the owner's demo Entra
tenant ([the result](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/8#issuecomment-6409098598); the full
record is in `VALIDATION.md`, "Ran for the real-tenant sign-in check"). No decision in this record changed.

- **Observed:** all seven calls answered as written (`401` for a missing, junk and wrong-audience token, `404` and `200` for
  a valid one, `403` when a required role was not held); the person-only check counted the token as a signed-in person;
  the start-up refusal exited 3 with nothing listening; and a real version 2.0 token carried `iss`
  `https://login.microsoftonline.com/<tenant>/v2.0`, `aud` equal to the API's client id, `scp` `access_as_user` and `roles`
  `CloudCrawler.Access`. The `roles` claim therefore looks as assumed.
- **Not verified:** HTTPS ingress (Container Apps) behind a public host name with `CC_ALLOWED_HOSTS`; a token from an
  application permission; a user who is not assigned when "Assignment required?" is on; an expired token; a token from
  another tenant; signing-key rotation; the `api://<app id>` audience form and the version 1.0 `iss` form; and the `idtyp`
  claim (the run did not report it). Only the demo tenant was used, so this says nothing about production.
- Ticket [#8](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/8) was closed as completed on 2026-10-26.

## Rollback or revisit trigger

Set `CC_AUTH_MODE=off` (and remove the `CC_ENTRA_*` settings) to return to the lab behaviour; no data changes. Revisit
when: the managed-identity / on-behalf-of HTTP transport lands (the token validated here may become the assertion
that flow exchanges), a client-application allow-list or per-role authorisation is wanted, a sovereign cloud is
needed, or Entra changes the token claims this relies on (`oid`, `tid`, `scp`, `idtyp`).
