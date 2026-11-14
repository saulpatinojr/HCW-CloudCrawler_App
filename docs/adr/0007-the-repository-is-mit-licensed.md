# 0007. The repository and the cloud-crawler-core engine are MIT-licensed

- **Status:** Accepted
- **Date:** 2026-11-14
- **Owners:** Workload owner
- **Issue:** [saulpatinojr/HCW-HybridCloudWorks#1707](https://github.com/saulpatinojr/HCW-HybridCloudWorks/issues/1707)
  (the licensing review of the App and AddOn repositories); the owner's answer "option 1" in the session of 2026-11-14

## Context

This repository has been MIT since it was created: `LICENSE` is the MIT License with "Copyright (c) 2026 Hybrid Cloud
Works", both `pyproject.toml` files (the appliance's and `packages/cloud-crawler-core/pyproject.toml`) declare
`license = "MIT"`, and since 2026-11-14 `NOTICE` says so too. But no decision record said it, unlike the sibling
repositories:

| Repository | Licence | Where the decision is recorded |
| --- | --- | --- |
| HCW-CloudAssessor_App | MIT | `REVIEW.md` R-003, the owner's decision of 2026-10-25 |
| HCW-MigrateOrchestrator_App | MIT | `docs/adr/ADR-0016-mit-license.md`, amended 2026-11-14 |
| HCW-NetworkEyes_App | Apache License 2.0 | `REVIEW.md` R-020, the owner's decision of 2026-10-25 |
| HCW-CloudCrawler_App (this repository) | MIT | this record |

All four AddOn repositories are MIT. The lab edition, HCW-CloudCrawler_AddOn, installs the engine wheel released here
unchanged (ADR 0002), so the engine's licence is also what the lab edition receives.

The owner was asked on 2026-11-14 whether to record this repository's licence, with the table above shown, and noting
that NetworkEyes differs on purpose. The owner chose to record it as MIT.

## Decision

The repository, including the `cloud-crawler-core` engine it releases, is licensed under the MIT License, as `LICENSE`
states. The wheel's package metadata keeps declaring `MIT`. NetworkEyes App's Apache License 2.0 is that repository's
own deliberate choice (R-020 there) and does not set a pattern this repository follows.

## Alternatives considered

| Alternative | Benefits | Drawbacks | Reason not selected |
| --- | --- | --- | --- |
| Record nothing | No change | The licence rests on the files alone, unlike the siblings | The owner asked for a record |
| Apache License 2.0, as NetworkEyes App | Explicit patent grant | A relicence of code that has shipped as MIT; differs from CloudAssessor, MigrateOrchestrator and every AddOn | Not asked for; MIT already in effect |

## Consequences

- Nothing changes in the code, the wheel or the images: this records what is already in effect.
- Anyone may use, copy, change and redistribute the code and the engine wheel, keeping the copyright and permission
  notice, with no warranty (the MIT terms).
- `NOTICE` keeps naming third-party material that is not under this licence (Microsoft's Azure MCP Server, used at run
  time and not redistributed; the contract snapshot of its tool list) and the trademarks.

## Validation

`LICENSE` is the MIT License; `pyproject.toml` and `packages/cloud-crawler-core/pyproject.toml` declare
`license = "MIT"`; `NOTICE` line 2 says "Licensed under MIT (see LICENSE)". All read on `main` on 2026-11-14.

## Rollback or revisit trigger

Only the owner can change the licence. A change would be a new record that supersedes this one, and it would reach the
lab edition through the next engine release, so it needs an entry in HCW-CloudCrawler_AddOn's
`docs/whats-new-upstream.md`.
