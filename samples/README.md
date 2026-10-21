# Samples

Fictional only. Subscription `00000000-0000-0000-0000-000000000001`, resource
names `hcw-sample-*`, except storage accounts, whose names Azure forbids a
hyphen in: those are `hcwsamplestprod01` and `hcwsamplestdev01`. Nothing here
was exported from a real tenant.

| File | What it is |
| --- | --- |
| `sample-resource-graph.json` | A portal-shaped Azure Resource Graph export (`{count, data}`) of a small estate: two SQL databases (one zone redundant, one not) and their SQL server (public access enabled, no private endpoint), two storage accounts (ZRS in prod with an approved private endpoint, LRS in dev), an App Service plan and a web app in the wrong region with no owner tag and no identity, a PostgreSQL flexible server, a Cosmos DB account with one non-zone-redundant secondary location and no private endpoint, an AKS cluster across three zones, a zonal-less VM, a zone-redundant public IP and a Key Vault with an approved private endpoint. |
| `decision-zone-redundancy.json` | The `adr_create` input for decision D-0001 of the website proposal: production data-platform resources must be zone redundant, as one `zone-redundancy` claim scoped by `env=prod`. It arrives as a draft; the scenarios accept it with `adr_accept` and the placeholder actor `00000000-0000-0000-0000-000000000011`. |
| `decision-azure-observations.json` | The `adr_create` input for "production platform observations": `advisor-findings`, `retirement-exposure` and `policy-assignment-present` claims over the recorded Azure MCP results. |
| `azure-mcp/*.json` | Recorded Azure MCP Server 3.0.0 results the recorded host replays (`CC_AZMCP_MODE=recorded`): `subscription_list`, `group_list`, `advisor_recommendation_list` (one `New` and one `Dismissed` high-impact reliability record; a separate recording with one service retirement dated 2027-03-31 against `hcw-sample-redis-01`) and `policy_assignment_list`. Each file carries the tool, the request arguments (`*` matches any value), the server identity and the `structuredContent`. The shapes are the server's result records on the `release/azure/3.x` branch as read on 2026-10-21; the values are fictional and were written by hand, not captured from a live server. |
| `decision-wave-one.json` | The `adr_create` input for the "production platform baseline": six claims, one per wave-one detector other than zone redundancy (public access disabled, private endpoint present, managed identity, owner tag, region `centralus`, zone-redundant storage SKU). |

The acceptance test `tests/acceptance/test_acceptance_zone_redundancy.py`
feeds the first decision through the MCP server and expects
`hcw-sample-sql-01` and `hcw-sample-cosmos-prod-01` to be contradicted,
`hcw-sample-sql-02`, `hcwsamplestprod01` and `hcw-sample-pg-prod-01` to be
supported, and every other resource to be not applicable.
`tests/acceptance/test_acceptance_wave_one.py` feeds the second and expects
the verdicts in `tests/acceptance/golden/wave-one.verdicts.json`: the SQL
server and the Cosmos DB account lack a private endpoint, the SQL server and
the web app allow public access, and the web app has no identity, no owner
tag and the wrong region. `tests/acceptance/test_acceptance_azure_mcp.py`
runs `collection_run_azure` on the recorded host against the third decision
and expects the SQL database's `New` Advisor record contradicted, the Cosmos
DB account's `Dismissed` one noted as accepted risk, the cache's retirement
contradicted with a retirement-kind proposal due 2027-03-31, and the
baseline initiative assignment supported.
