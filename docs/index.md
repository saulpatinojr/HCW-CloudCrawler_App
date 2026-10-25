# Cloud Crawler, App edition

Cloud Crawler is [Hybrid Cloud Works](https://hybridcloudworks.com)' Azure architecture appliance. It keeps a written
record of what an architecture team decided, checks those decisions against what Azure reports, and tells the team
where the two have drifted apart.

!!! warning "Not production software"
    This is the first implementation slice. The program answers `GET /api/health` with `"production": false`, and
    this site says the same. It is meant for a trusted lab network and for reading the design, not for a live
    environment. The page [Known limitations](known-limitations.md) lists exactly what is missing.

## What it does, in plain words

Think of it as a notebook with a built-in checker. The notebook holds five kinds of record:

| Record | What it is |
| --- | --- |
| **Evidence** | A fact with its source: what Azure reported, what a document says, or what a decision states. Every record is hashed (given a fingerprint so a change is noticed), redacted and dated, and carries where it came from and when it expires. |
| **Decision record** | An architecture decision record (ADR, a short written design decision): the context, the choices considered and what follows from the choice. Each claim in it is tied to a rule-based checker called a detector. |
| **Drift finding** | The verdict of one claim against the current evidence: `supported`, `contradicted`, `unknown` or `not-applicable`. A claim the evidence cannot answer is `unknown`, and `unknown` lowers the coverage figure, never the score. |
| **Contradiction** | A dated record that a claim is contradicted by evidence, listing the evidence it rests on. |
| **Review proposal** | What a contradiction, a retirement notice, an Azure Advisor finding or a cost ceiling asks the architects to decide, with an approval trail. |

The verdicts come from detectors, which are ordinary code with fixed rules. A language model never decides a verdict.

Azure MCP Server (Microsoft's server that lets programs read Azure) is the source of truth for what Azure reports. It is
pinned to version 3.0.0 and runs as a separate process. This appliance is the source of truth for what was decided,
claimed, contradicted, reviewed and approved. See [ADR 0001](adr/0001-pin-azure-mcp-server-3-0-0.md).

## There is no screen

This edition has no user interface of its own. It is an HTTP API (`/api/health`) and an MCP server (`/mcp`, MCP being
the Model Context Protocol that AI tools use to call programs) that other programs call. The screens people use belong
to the Hybrid Cloud Works website and to the AddOn's small web pane.

## Two editions

| Edition | What it is | Where |
| --- | --- | --- |
| **App** (this site) | The upstream product and reference implementation. It owns the engine and the appliance, and it is the only edition that can talk to Azure. | [HCW-CloudCrawler_App](https://github.com/saulpatinojr/HCW-CloudCrawler_App) |
| **AddOn** | The lab edition the website uses. It adopts the engine from this repository unchanged and can never reach Azure. | [HCW-CloudCrawler_AddOn](https://github.com/saulpatinojr/HCW-CloudCrawler_AddOn) |

The engine (`packages/cloud-crawler-core`) depends on one library only, `pydantic`, and moves downstream unchanged
([ADR 0002](adr/0002-engine-moves-downstream-unchanged.md), [ADR 0003](adr/0003-the-addon-never-calls-azure.md)).

## Where to read next

- [Security](security.md): who can call the appliance, what it refuses to do, and how to report a problem.
- [Known limitations](known-limitations.md): what is not built, not tested or not decided yet.
- [Release notes](release-notes.md): what changed in each version.
- [Decisions](adr/README.md): the architecture decision records.
- The [repository README](https://github.com/saulpatinojr/HCW-CloudCrawler_App#readme) has the install and run steps
  until those pages join this site.

The code is licensed under the [MIT License](https://github.com/saulpatinojr/HCW-CloudCrawler_App/blob/main/LICENSE).
