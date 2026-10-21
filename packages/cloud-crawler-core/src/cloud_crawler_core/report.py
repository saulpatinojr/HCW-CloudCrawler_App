"""The report bundle for one decision's evaluation: `report.md`, `report.json` and `NOT-AN-AUDIT.md`, as text.

The bundle carries the decision, the findings and the open proposals. Identifiers inside it are the caller's own
(the report goes back to whoever holds the session), so nothing is redacted here beyond what ingestion already did.
"""

from __future__ import annotations

import json

from cloud_crawler_core import __version__
from cloud_crawler_core.models import DecisionRecord, DriftResult, Verdict

NOT_AN_AUDIT = """# Not an audit

This bundle is produced by Cloud Crawler, an architecture evidence and drift tool. It is not an audit, not a
compliance attestation and not a security assessment. Every verdict is the deterministic result of a named detector
over the evidence that was handed in, and nothing more:

- `supported` and `contradicted` say what the evidence showed at the time it was retrieved; evidence expires.
- `unknown` means the evidence could not say. Unknown lowers coverage, never score.
- `not-applicable` means the resource is outside the claim's selector or the detector has no reader for its type.
- Evidence that was uploaded rather than observed is labelled `imported` and carries a lower confidence.

Decisions, claims and their scopes are the author's. Cloud Crawler does not change anything in Azure.
"""


def bundle(decision: DecisionRecord, result: DriftResult) -> dict[str, str]:
    """File name -> content."""
    report = {
        "engine": {"name": "cloud-crawler-core", "version": __version__},
        "decision": decision.model_dump(mode="json", by_alias=True),
        "result": result.model_dump(mode="json", by_alias=True),
    }
    return {
        "report.md": _markdown(decision, result),
        "report.json": json.dumps(report, indent=2, sort_keys=True) + "\n",
        "NOT-AN-AUDIT.md": NOT_AN_AUDIT,
    }


def _markdown(decision: DecisionRecord, result: DriftResult) -> str:
    s = result.summary
    lines = [
        f"# Drift report: {decision.title}",
        "",
        f"Decision `{decision.decisionId}` version {decision.version}, status {decision.status.value}. "
        f"Evaluated {result.evaluatedAt.isoformat()} by cloud-crawler-core {__version__}. **Not an audit.**",
        "",
        "| Supported | Contradicted | Unknown | Not applicable | Score | Coverage |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| {s.supported} | {s.contradicted} | {s.unknown} | {s.notApplicable} | "
        f"{'n/a' if s.score is None else s.score} | {'n/a' if s.coverage is None else s.coverage} |",
        "",
        "## Findings",
        "",
        "| Verdict | Claim | Resource | Observed | Expected | Reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    order = {Verdict.CONTRADICTED: 0, Verdict.UNKNOWN: 1, Verdict.SUPPORTED: 2, Verdict.NOT_APPLICABLE: 3}
    for f in sorted(result.findings, key=lambda x: (order[x.verdict], x.resourceId or "")):
        lines.append(
            f"| {f.verdict.value} | {f.claimId} | {f.resourceId or '(decision)'} | "
            f"{json.dumps(f.observed, sort_keys=True)} | {json.dumps(f.expected, sort_keys=True)} | "
            f"{f.unknownReason or ''} |"
        )
    if result.proposals:
        lines += ["", "## Review proposals", ""]
        for p in result.proposals:
            lines.append(f"- **{p.title}** ({p.kind.value}, {p.status.value}): {p.rationale}")
            for action in p.recommendedActions:
                lines.append(f"  - {action.action}")
    lines.append("")
    return "\n".join(lines)
