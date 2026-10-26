# 0005. Terraform state and plan are read through a provider-type table, and what Terraform cannot say stays unknown

- **Status:** Proposed (becomes Accepted when the pull request that adds it is merged)
- **Date:** 2026-10-26
- **Owners:** Workload owner and architecture owner
- **Issue:** [HCW-CloudCrawler_App#54](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/54), which follows from the lab
  edition's [issue 16](https://github.com/saulpatinojr/HCW-CloudCrawler_AddOn/issues/16) and the website proposal, section 13.3

## Context

The engine has accepted the evidence kinds `tf-state` and `tf-plan` since 0.1.0 but only stored them redacted and
unparsed, so every claim about a Terraform resource was `unknown`. The website promises "upload an export of your Azure
resources or your Terraform and see where what is built has drifted". [ADR 0002](0002-engine-moves-downstream-unchanged.md)
says engine work is written here first and reaches the lab edition at a release, so the reading of Terraform belongs in
`packages/cloud-crawler-core`, in the same shape every resource detector already reads: `NormalizedResource`, named the
way Azure Resource Graph names things.

Terraform is a different kind of source from a Resource Graph export. A state or a plan describes what Terraform
manages (a plan: what it would build), in the provider's attribute names, with values it marks sensitive, with values a
plan cannot know until apply, and without the things Azure adds on its own. Three rules of the program decide how it is
read: verdicts come from detectors, never a guess; unknown lowers coverage, never the score; and no secret is stored.

## Decision

1. **Two documents are read.** `tf-state` is a Terraform state file of version 4. `tf-plan` is the JSON of a plan
   (`terraform show -json`), `format_version` 1.x. For a plan, the rows come from `resource_changes[].change.after`, one
   per object that still exists after the change (a deletion has nothing after it); if the plan has no `resource_changes`,
   the same rows come from `planned_values`. Both stay `imported` evidence with the confidence of an upload (0.80, capped
   at 0.74 when unauthenticated) and the seven-day expiry of an import.
2. **A table decides what is read.** `normalize/terraform_types.py` maps 31 azurerm resource types to 25 Azure types,
   including every Azure type a wave-one detector reads (a test fails if one is added without a mapping). A mapping
   copies only the values it names, in Resource Graph's spelling: `azurerm_storage_account` gives `sku.name` from
   `account_tier` and `account_replication_type`, `properties.publicNetworkAccess` from the boolean
   `public_network_access_enabled` (azurerm 3 and 4) or the text `public_network_access` (azurerm 5), and so on. Whole
   blocks are never copied. The table is a contract like the detector ids: types are added, never renamed or dropped
   (`tests/snapshots/terraform-type-table.json`). A node pool resource joins its cluster's `agentPoolProfiles`, as Resource
   Graph lists every pool on the cluster, and a database takes its server's location.
3. **What Terraform cannot say stays unknown.** A value is mapped only when its attribute is present and of the expected
   type. Absent (not in the provider's schema, or unknown until apply), null where null would be a guess, of the wrong
   type, or sensitive: the property is left out and the detector that reads it answers `unknown` and names it. Three
   fields mean "none" in an export when omitted (`identity`, `tags`, `zones`), so a row lists the ones the document
   cannot answer in a new `NormalizedResource.notCarried`, and the three detector readers that treat absence as "none"
   answer `unknown` for them (`detectors.base.not_carried`, and a test that fails if a detector module reads one of the
   fields without it).
4. **Sensitive values are withheld before anything is read, and the document is never stored.** `sensitive_attributes`
   (state) and `after_sensitive` (plan) are honoured; a mark that does not fit its value, or cannot be read, withholds
   the value or skips the instance. The stored payload is the rows and a content-free summary (counts and Terraform type
   names that look like type names); the raw document is hashed, redacted and discarded.
5. **The document is bounded before anything walks it.** At most 100 levels of nesting and 1,000,000 values, checked
   iteratively before hashing and redaction (both recurse), and at most `max_rows` rows. The normaliser uses no regular
   expression, so nothing in it is quadratic on a crafted string (a test reads the module's imports).
6. **A row without an Azure id** (a resource the plan creates) is keyed `terraform:<address>`, correlated as a
   `terraform-address`, and takes the subscription the caller declared in the evidence subject, because a plan does not
   know it. Without a declared subscription it is outside a subscription-scoped decision.
7. **The attribute names were read from the provider documentation**, azurerm 3.117.1, 4.81.0 and 5.11.0
   (`website/docs/r/<type>.html.markdown` at those tags, 2026-10-26). A name a provider version does not have reads as
   absent.

Not done in this slice, and recorded in the known limitations: private endpoints (a separate resource, with an approval
state the resource's own attributes do not carry); data sources; the `terraform show -json` form of a state; providers
other than hashicorp/azurerm (for example azapi); and Azure types no wave-one detector reads.

## Alternatives considered

| Alternative | Benefits | Drawbacks | Reason not selected |
| --- | --- | --- | --- |
| Read the Terraform configuration (HCL) | Sees what is intended before a plan exists | Needs variables, modules and providers evaluated; says nothing about what is built | A state or a plan is what Terraform itself computed |
| Copy every attribute into `properties` and let detectors pick | No table to keep | Ships unvetted values (secrets among them) into the ledger; detectors read Resource Graph names, not provider names | A table that names each value is also the list of what is stored |
| Default an absent attribute (no identity, no tags, no zones) | Fewer unknowns | A plan that cannot yet know its tags would be reported as missing them: a false contradiction | "Unknown lowers coverage, never score" |
| Correlate `azurerm_private_endpoint` resources into the protected resource | The four private endpoint claims would be answered | The approval state of a connection is not in the document, and a private endpoint managed elsewhere is invisible, so it could only ever say "supported" | Left as `unknown` until there is a way to say "not known to Terraform" |
| Only `planned_values` for a plan | One walk | No per-object action, no `after_unknown`, and the less used route for policy tools | `resource_changes` is primary; `planned_values` is the fallback and a test keeps the two equal for the sample |
| Reserve a key inside `properties` for "not carried" | No model change | Hides a contract in a free-form dictionary | An optional field with a default is additive |

## Consequences

- The lab edition adopts this at the next engine release with no route change (its door already accepts both kinds). Its
  `docs/whats-new-upstream.md` is updated in its adoption pull request.
- **Behaviour change for the two kinds:** the stored payload is now `{"resources": [...], "terraform": {...}}` and no
  longer the redacted document, so `evidence_get` returns rows. A document that is not a version 4 state or a 1.x plan,
  which was stored unread before, is now refused with `invalid_request`.
- `NormalizedResource` gains `notCarried` (an empty list for a Resource Graph export). A Resource Graph export is read
  exactly as before.
- Security: sensitive values never leave the normaliser; a hostile document is refused by size and depth before it is
  walked; the redaction patterns run first and are linear ([#53](https://github.com/saulpatinojr/HCW-CloudCrawler_App/issues/53)).
- Cost of keeping it right: the table follows the azurerm provider. A new major version that renames an attribute reads
  as absent (unknown), not wrong; the documentation date in `terraform_types.py` says when the names were last checked.
- A plan is not what exists. Its rows are labelled by the evidence kind and the summary says `tf-plan`, but a verdict from
  a plan is a verdict on what Terraform would build.

## Validation

`packages/cloud-crawler-core/tests` (`test_terraform_normalize.py`, `test_terraform_ingest.py`, `test_not_carried.py`,
`test_terraform_type_table.py`) and `tests/acceptance/test_acceptance_terraform.py`, which run the sample estate
(`samples/terraform/`) through the MCP server as a state and as a plan and compare the verdicts with the Resource Graph
export of the same estate: identical for every claim whose properties Terraform carries, `unknown` with the property
named for the four private endpoint claims, nothing else different. Mutation checks and what was not verified are in
`VALIDATION.md`.

## Rollback or revisit trigger

Revert the pull request: the two kinds go back to being stored unparsed. Revisit when azurerm changes an attribute the
table reads, when the owner wants private endpoints correlated (with a way to say "not known to Terraform"), or when a
second provider (azapi) is needed.
