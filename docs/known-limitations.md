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

## What redaction does not promise

When a payload arrives, and when an error message is written to the log, the appliance replaces text that has a secret's
shape with `<redacted>`. The shapes it knows are a storage account key or shared access key (`AccountKey=`,
`SharedAccessKey=`), a shared access signature (`sig=`), a GitHub token (`ghp_`), a JSON web token (the `eyJ...` text
that sign-in tokens are made of), a private key header, and any value stored under a key name such as `password` or
`token`. It is not a general secret finder: a secret in a shape it does not know is stored as it arrived.

- **Only the header of a private key is replaced.** The key text that follows the header line is not.
- **Only text is scanned.** Field names (apart from the denied names such as `password`) and values that are not text,
  such as bytes, are stored as they arrived.
- **The third part of a JSON web token stays readable.** A token has three parts joined by dots. Redaction covers the
  first two and stops there, so the signature at the end of a normal token is not redacted. This has always been so, and
  the fix for [ticket #53](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/53) did not change it.
- **A key value that runs straight into a token swallows the token's first part.** The values of `AccountKey=`,
  `SharedAccessKey=` and `sig=` take letters and digits, so `sig=<24 letters>eyJ...` has no break where the token
  starts: the value takes the first part, and the dot and the second part stay readable. This was so before the fix too.
- **Two secrets with nothing between them can be cut at a different place than before.** The case that has been seen
  is a token whose second part runs straight into a keyword, written like `<token>.<part>AccountKey=<value>` (the same
  with `SharedAccessKey=`, `sig=` and the private key header): the token takes everything up to the `=` (for the header,
  up to its space), so the key's value stays readable. The text before the fix behaved the same way unless a `ghp_`
  match happened to come first, so this is not new, and someone who controls the text in front of a secret can build it
  on purpose. The tests build random texts of this kind, count them (27 in 300,000 with the seed they use), and fail if
  the count rises above a stated ceiling or if anything else is lost. Those tests are samples, not a proof.
