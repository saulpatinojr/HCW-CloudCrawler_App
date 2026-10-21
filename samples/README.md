# Samples

Fictional only. Subscription `00000000-0000-0000-0000-000000000001`, resource
names `hcw-sample-*`. Nothing here was exported from a real tenant.

| File | What it is |
| --- | --- |
| `sample-resource-graph.json` | A portal-shaped Azure Resource Graph export (`{count, data}`) of a small estate: two SQL databases (one zone redundant, one not), two storage accounts (ZRS in prod, LRS in dev), an App Service plan, a PostgreSQL flexible server, a Cosmos DB account with one non-zone-redundant secondary location, an AKS cluster across three zones, a zonal-less VM, a zone-redundant public IP and a Key Vault. |
| `decision-zone-redundancy.json` | The `adr_create` input for decision D-0001 of the website proposal: production data-platform resources must be zone redundant, as one `zone-redundancy` claim scoped by `env=prod`. |

The acceptance test `tests/acceptance/test_zone_redundancy.py` feeds both
through the MCP server and expects `hcw-sample-sql-01` and
`hcw-sample-cosmos-prod-01` to be contradicted, `hcw-sample-sql-02`,
`hcwsamplestprod01` and `hcw-sample-pg-prod-01` to be supported, and every
other resource to be not applicable.
