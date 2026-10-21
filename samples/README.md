# Samples

Fictional only. Subscription `00000000-0000-0000-0000-000000000001`, resource
names `hcw-sample-*`. Nothing here was exported from a real tenant.

| File | What it is |
| --- | --- |
| `sample-resource-graph.json` | A portal-shaped Azure Resource Graph export (`{count, data}`) of a small estate: two SQL databases (one zone redundant, one not) and their SQL server (public access enabled, no private endpoint), two storage accounts (ZRS in prod with an approved private endpoint, LRS in dev), an App Service plan and a web app in the wrong region with no owner tag and no identity, a PostgreSQL flexible server, a Cosmos DB account with one non-zone-redundant secondary location and no private endpoint, an AKS cluster across three zones, a zonal-less VM, a zone-redundant public IP and a Key Vault with an approved private endpoint. |
| `decision-zone-redundancy.json` | The `adr_create` input for decision D-0001 of the website proposal: production data-platform resources must be zone redundant, as one `zone-redundancy` claim scoped by `env=prod`. It arrives as a draft; the scenarios accept it with `adr_accept` and the placeholder actor `00000000-0000-0000-0000-000000000011`. |
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
tag and the wrong region.
