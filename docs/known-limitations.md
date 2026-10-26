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

## Terraform state and plan

The engine reads a Terraform state file (version 4) and the JSON of a plan (`terraform show -json`, format 1.x) as
evidence ([ADR 0005](adr/0005-terraform-evidence-is-read-through-a-provider-type-table.md)). What it does not do:

- **It says only what Terraform says.** A property that Terraform's document does not carry, or carries as null or as
  something this version does not read, makes the detector answer `unknown` with the property named. The four private
  endpoint claims of the sample estate are `unknown` for this reason: a private endpoint is a separate Terraform
  resource, and whether its connection is approved is not in the document.
- **A plan is not what exists.** Verdicts from a plan are about what Terraform would build. A plan row never replaces
  a row from a Resource Graph export, an Azure MCP result or a state of the same resource, whichever came last, and a
  verdict that rests on plans alone never closes an open contradiction as fixed (the plan still evaluates, and it can
  open one). A value that is only known after apply (a new resource's id, tags built from another resource) is not
  read, and the row says so: a claim about those tags is `unknown`, and a resource with no Azure id yet is named by its
  Terraform address. When a plan has no `resource_changes` and is read from `planned_values`, which marks nothing as
  unknown, its tags, identity and zones are always `unknown`.
- **A state is not what Azure holds.** It describes what Terraform last applied or refreshed. A resource changed by hand
  since, or created outside Terraform, is not in it, and a state row still replaces an earlier observed row of the same
  resource, as a later export would.
- **A resource the plan creates belongs to the subscription the caller declares.** The plan does not know it. Without
  a declared subscription (the evidence subject's `subscriptionId`), such a resource is outside any decision scoped by
  subscription. A tag selector (a claim's, or a decision scope's) cannot be applied to a row whose tags are not known:
  the claim answers `unknown` for the row.
- **Only the resources Terraform manages in that one document.** Another state file, or a resource created by hand, is
  not there. A cluster's node pools that live in another state file are not counted, and a node pool that cannot be
  placed on a cluster (its cluster is not known until apply) makes every cluster in the document answer `unknown` for
  zones.
- **Thirty-one azurerm resource types** become rows (the ones the wave-one detectors read; `azurerm_storage_account`,
  `azurerm_key_vault`, `azurerm_kubernetes_cluster` and so on), and a 32nd, `azurerm_kubernetes_cluster_node_pool`,
  joins its cluster. Another type, a data source, an object that is being destroyed and a provider other than
  hashicorp/azurerm (for example azapi) make no row; the evidence record's summary counts them by Terraform type name.
- **Sensitive values** are read from the markers Terraform writes. A state or plan from a Terraform that writes none
  cannot say what is sensitive; only the values the table names are ever copied, and the summary's `markersAbsent` says
  how many instances had no markers.
- **Not run against a real azurerm state.** The attribute names come from the azurerm documentation (3.117.1, 4.81.0 and
  5.11.0), and the structure of the two documents was checked with real Terraform 1.16.6 output of the built-in
  `terraform_data` resource, but nothing was produced by the azurerm provider itself: there is no Azure access in the
  authoring session. The fixtures are fictional.
- **The `terraform show -json` form of a state** (a `values` tree instead of `resources`) is refused with a message
  that points to `tf-plan` or to the state file.
- **Size.** A document is refused above 100 levels of nesting or 1,000,000 values, and above `CC_MAX_ROWS` rows and
  folded node pools together (the same setting as for a Resource Graph export). A number that is not finite, an integer
  of more than 4,300 digits or text with a lone surrogate is refused with `invalid_request`. These limits apply to the
  Terraform kinds. For the other kinds the HTTP door's JSON parser stops a document nested more than about 200 levels
  (`recursion limit exceeded`), but a caller of the engine that builds its own objects does not pass through it.

## What the detectors can see

- The detectors read what an Azure Resource Graph export carries. A property an export leaves out answers `unknown` with
  the property named, never a guessed verdict. Diagnostic settings, locks and sub-resource encryption state are not in
  an export, so claims about them stay `unknown`.
- A single virtual machine row answers `unknown` for zone redundancy, because redundancy belongs to a set of
  instances, and this slice has no set-level reader.
- The Azure observation detectors ignore tag selectors, because Advisor and policy records carry no tags.
- The caller class in each tool's metadata (`meta.caller`) is declared here and enforced by the website's orchestrator.
  This server only checks that a call for a person names an actor.
