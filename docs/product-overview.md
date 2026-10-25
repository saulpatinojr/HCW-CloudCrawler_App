# Product overview

Cloud Crawler keeps an architecture team honest. The team writes down a decision, for example "our production databases
are zone-redundant", and states it as a claim a program can check. Cloud Crawler then compares each claim with what
Azure reports and says whether the claim still holds.

> **First slice, not production.** The program reports `"production": false` on `GET /api/health`. Read [Known limitations](known-limitations.md) before relying on any answer.

## The idea in four steps

1. **Collect evidence.** Azure facts come in as evidence records: from an Azure Resource Graph export you hand in, or
   from Azure MCP Server 3.0.0 through the standard collection sequence. Each record keeps where it came from, a hash of
   the original, and an expiry time. Secrets and personal values are redacted as the record arrives.
2. **Write decisions with claims.** A decision record (an ADR, a short written design decision) lists its claims. A claim
   names a detector (a fixed, rule-based check), the kind of resources it covers, and the expectation, such as "equals
   `true`" or "is one of these regions".
3. **Evaluate drift.** The drift engine runs each claim's detector over the current evidence and gives one verdict per
   claim and resource: `supported`, `contradicted`, `unknown` or `not-applicable`. The decision gets a score and a
   coverage figure.
4. **Review what changed.** A contradiction opens a review proposal. A person decides it. The decision and its approval
   trail are kept.

## How to read a verdict

| Verdict | Meaning |
| --- | --- |
| `supported` | The evidence says the claim holds for this resource. |
| `contradicted` | The evidence says the claim does not hold. A dated contradiction record is opened. |
| `unknown` | The evidence does not answer the question, for example a property the export left out. |
| `not-applicable` | The resource is outside what the claim covers. |

The score counts only what could be answered, weighted by severity (critical 4, high 3, medium 2, low 1). **Unknown
lowers the coverage figure and never the score**, so a gap in the evidence cannot make a decision look worse or better
than the facts allow. A language model never decides a verdict: detectors are plain code, and the same evidence always
gives the same answer.

## The detectors

| Detector | What it checks |
| --- | --- |
| `zone-redundancy` | Whether SQL databases, storage accounts, App Service plans, PostgreSQL flexible servers, Cosmos DB accounts, AKS clusters, virtual machine scale sets and public IP addresses spread across zones. A single virtual machine answers `unknown`. |
| `public-access-disabled` | Whether public network access is off (twelve data, secret, messaging and compute types). |
| `private-endpoint-present` | Whether an approved private endpoint connection exists. |
| `managed-identity` | Whether the resource has a managed identity of the expected type. |
| `tag-required`, `sku-allowed`, `region-allowed` | Valued checks that compare a reading with `eq`, `neq`, `in`, `exists`, `absent`, `gte` or `lte`. |
| `advisor-findings` | An Azure Advisor recommendation that is `New` is a contradiction; `Dismissed` and `Postponed` are accepted risk. |
| `retirement-exposure` | Opens a retirement review with the date and Advisor's remediation. |
| `policy-assignment-present` | Whether the Azure Policy definition or initiative the claim names is assigned at the scope. |

Detector ids are only ever added, never renamed, so a claim written today keeps its meaning.

## The tools other programs call

The appliance serves 14 MCP tools (15 when an Azure host is configured). Names follow `namespace_action`. Each tool
declares whether it only reads, and whether it needs a person.

| Tools | Who may call | What they do |
| --- | --- | --- |
| `adr_create`, `adr_get`, `adr_list` | model | Create a draft or proposed decision with its claims, read it, list decisions. |
| `evidence_ingest`, `evidence_list`, `evidence_get` | model | Hand in an Azure Resource Graph export, list and read evidence. |
| `drift_evaluate`, `drift_list`, `contradiction_list` | model | Run the detectors, read verdicts and open contradictions. |
| `review_propose`, `review_list`, `review_get` | model | Open and read review proposals. |
| `adr_accept`, `review_decide` | **human** | Accept a decision, decide a review. These record only a hash of the person's object id. |
| `collection_run_azure` | **human** | Run the standard collection sequence through Azure MCP. The one tool that calls Azure, so it exists only when a host is configured. |

"Model" means an AI assistant may call it. "Human" means a person must be behind it: with sign-in on, the appliance
checks that the token is a person's delegated token. See [Security](security.md).

## What it is not

- **Not an audit.** Every report bundle carries a `NOT-AN-AUDIT.md` note saying so.
- **Not a scanner.** It checks the claims you wrote, not everything that could be wrong.
- **Not a screen.** It has no user interface; the website and the AddOn's web pane provide the screens.

## Where to go next

[Architecture](architecture.md) shows how the pieces fit, and [Known limitations](known-limitations.md) lists what is
not built or not tested yet.
