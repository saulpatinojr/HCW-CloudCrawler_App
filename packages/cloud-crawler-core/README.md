# cloud-crawler-core

The Cloud Crawler engine. Pure functions over pydantic models: evidence records
with canonical hashing, redaction and provenance; decision records with claims;
deterministic drift detectors; the drift engine; an in-memory ledger; and the
report bundle. It depends on pydantic only: no HTTP client, no cloud SDK, no
I/O beyond what a caller hands in.

It is seeded and versioned here, in `HCW-CloudCrawler_App`, and adopted by
`HCW-CloudCrawler_AddOn` unchanged (ADR 0002).

| Module | What it holds |
| --- | --- |
| `models` | Evidence, SourceProvenance, CollectionRun, DecisionRecord, Alternative, Claim, CostEstimate, DriftFinding, Contradiction, ReviewProposal, Approval, NormalizedResource |
| `hashing` | canonical JSON and `sha256:` digests |
| `redaction` | payload redaction (secret-shaped values, denied keys) and the content-free log guard |
| `normalize` | one normaliser per evidence kind; `resource_graph` for Azure Resource Graph exports |
| `detectors` | the detector registry: `zone-redundancy`, `public-access-disabled`, `private-endpoint-present`, `managed-identity` (boolean questions) and `tag-required`, `sku-allowed`, `region-allowed` (valued: the claim's expectation compares the reading with `eq`, `neq`, `in`, `exists`, `absent`, `gte`, `lte`) |
| `drift` | `evaluate_decision`: claims × evidence → findings, contradictions, proposals, score and coverage |
| `ledger` | `InMemoryLedger` |
| `ingest` | the ingestion pipeline: validate, hash, redact, normalise, correlate, assign confidence and expiry |
| `report` | the bundle: `report.md`, `report.json`, `NOT-AN-AUDIT.md` |

Rules: unknown lowers coverage, never score; detector ids are only ever added,
never renamed; verdicts come from detectors, never from a model.
