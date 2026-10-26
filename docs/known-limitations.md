# Known limitations

This is the honest list of what this first slice does not do yet. It is a plain-words version of the "Known
limitations" section of
[VALIDATION.md](../VALIDATION.md), which also records every
check that was run and every check that was not.

> **Not production software.** `GET /api/health` reports `"production": false`. Use the appliance on a trusted lab network only.

## Not built yet

- **A hosted Azure connection.** The appliance talks to Azure MCP Server only as a child process over standard input and
  output (stdio), using the developer's own sign-in, or replays recorded fictional results. Running under a managed
  identity, or forwarding a person's token to a hosted server, is not implemented. `/api/health` therefore reports
  `azureConnectivity` as `not-configured`, `stdio-developer-credential` or `recorded`, never `managed-identity` or `obo`.
- **A saved ledger.** The ledger lives in memory and is lost when the program stops. It is not separated by tenant,
  user or session, so a second tenant must not share one appliance.
- **The cost-ceiling detector** and the `cost_estimate_attach` tool.
- **Live collectors** beyond the standard collection sequence, the operator pane (a screen) and Container Apps
  deployment.
- **A user interface.** There is none; see the [Home](../README.md) page.

## Not tested yet

- **Microsoft Entra sign-in has run against one real tenant, once.** On 2026-10-26 the README's sandbox runbook
  ("Checking sign-in against a real tenant") was run in the owner's demo tenant. All seven calls answered as written, the
  start-up refusal and the role check worked, and a real version 2.0 token carried the expected `iss`, `aud`, `scp` and
  `roles` values ([the result](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/8#issuecomment-6409098598),
  and the "Ran" entry in [VALIDATION.md](../VALIDATION.md)). Still not verified: HTTPS in front of the program
  (Container Apps or another ingress) behind a public host name; a token for a service (an application permission); a
  user who is not assigned when "Assignment required?" is on; an expired token; a token from another tenant; signing-key
  rotation; the `api://<app id>` form of the audience and the version 1.0 `iss` form (the valid token was version 2.0
  and carried the bare client id); and the `idtyp` claim, which the run did not report. Nothing outside the demo tenant
  was touched, so this says nothing about production.
- **The stdio host has not run against a live Azure MCP Server with a signed-in account.** The contract test starts the
  real 3.0.0 server and checks its tool list, but it makes no Azure call.
- **The recorded results are hand-written.** They were written from the 3.0.0 source with fictional values and have not
  been compared with a live capture.
- **The release pipeline has never run for a real release.** It has been rehearsed with a dry run that publishes
  nothing, but building, signing and publishing for a real `v*` tag is untested until the first tag.

## Sign-in gaps

Sign-in is **off by default**, and that is a decision, not an oversight ([ADR 0004](adr/0004-entra-token-validation-on-api-and-mcp.md)).
With it on, these gaps remain:

- No list of allowed client applications. Who can obtain a token is controlled in Entra with "Assignment required".
- Role checks are optional and coarse. With `CC_AUTH_REQUIRED_ROLES` empty (the default) any valid token for the tenant
  and audience can read, ingest, propose and evaluate. With roles listed, a token needs at least one of them in its
  `roles` claim, but that is one gate for the whole service, not a different permission per tool.
- Only the public Microsoft cloud is supported; sovereign clouds are not.
- No revocation: a stolen token works until it expires, as with any access token. No token binding, and no rate limit on
  failed sign-ins.
- A person's token proves consent, not attention: a service holding a person's token acts as that person.
- With sign-in off, the appliance refuses to start on any address except this machine's own, unless
  `CC_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true` is set on purpose. The container image listens on every interface and
  never sets that value, so `docker run` needs sign-in on or the explicit opt-out. Using the opt-out writes one warning
  line. The owner decided to build this on 2026-10-26 (ADR 0004, amendment).

## What the detectors can see

- The detectors read what an Azure Resource Graph export carries. A property an export leaves out answers `unknown` with
  the property named, never a guessed verdict. Diagnostic settings, locks and sub-resource encryption state are not in
  an export, so claims about them stay `unknown`.
- A single virtual machine row answers `unknown` for zone redundancy, because redundancy belongs to a set of
  instances, and this slice has no set-level reader.
- The Azure observation detectors ignore tag selectors, because Advisor and policy records carry no tags.
- The caller class in each tool's metadata (`meta.caller`) is declared here and enforced by the website's orchestrator.
  This server only checks that a call for a person names an actor.
