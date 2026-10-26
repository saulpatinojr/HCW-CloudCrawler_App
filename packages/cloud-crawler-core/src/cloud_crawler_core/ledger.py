"""An in-memory ledger: decisions, evidence, findings, contradictions, proposals and approvals, append-only except
for contradiction and proposal state. Both editions use it; the App edition swaps in a persistent one later behind
the same interface."""

from __future__ import annotations

from datetime import datetime

from cloud_crawler_core.models import (
    Approval,
    Contradiction,
    ContradictionResolution,
    DecisionRecord,
    DriftFinding,
    DriftResult,
    Evidence,
    EvidenceKind,
    ReviewProposal,
    Verdict,
)


class NotFound(KeyError):
    """A record that is not in this ledger. Callers answer 404; the id never reaches a log."""


class InMemoryLedger:
    def __init__(self) -> None:
        self.decisions: dict[str, DecisionRecord] = {}
        self.evidence: dict[str, Evidence] = {}
        self.findings: dict[str, DriftFinding] = {}
        self.contradictions: dict[str, Contradiction] = {}
        self.proposals: dict[str, ReviewProposal] = {}
        self.approvals: dict[str, Approval] = {}

    # decisions
    def add_decision(self, decision: DecisionRecord) -> DecisionRecord:
        self.decisions[decision.decisionId] = decision
        return decision

    def get_decision(self, decision_id: str) -> DecisionRecord:
        try:
            return self.decisions[decision_id]
        except KeyError:
            raise NotFound(decision_id) from None

    def list_decisions(self, *, status: str | None = None) -> list[DecisionRecord]:
        return [d for d in self.decisions.values() if status is None or d.status.value == status]

    def update_decision(self, decision: DecisionRecord) -> DecisionRecord:
        """Replace a decision in place (status changes, supersession). The id must already be in the ledger."""
        self.get_decision(decision.decisionId)
        self.decisions[decision.decisionId] = decision
        return decision

    # evidence
    def add_evidence(self, evidence: Evidence) -> Evidence:
        self.evidence[evidence.evidenceId] = evidence
        return evidence

    def get_evidence(self, evidence_id: str) -> Evidence:
        try:
            return self.evidence[evidence_id]
        except KeyError:
            raise NotFound(evidence_id) from None

    def list_evidence(self, *, kind: str | None = None, evidence_class: str | None = None) -> list[Evidence]:
        return [
            e
            for e in self.evidence.values()
            if (kind is None or e.kind.value == kind)
            and (evidence_class is None or e.evidenceClass.value == evidence_class)
        ]

    def evidence_for(self, decision: DecisionRecord, *, now: datetime | None = None) -> list[Evidence]:
        """Every record not yet expired. Scope filtering happens in the drift engine, resource by resource."""
        records = list(self.evidence.values())
        if now is not None:
            records = [e for e in records if e.expiresAt is None or e.expiresAt > now]
        return records

    # drift
    def record(self, result: DriftResult) -> DriftResult:
        """Keep every finding; merge contradictions by (claim, resource) so firstSeenAt survives re-evaluation; close
        an open contradiction as `fixed` when the same claim and resource now evaluate `supported`, unless the
        verdict rests on Terraform plans alone or cites a record the ledger does not hold."""
        for finding in result.findings:
            self.findings[finding.findingId] = finding
        existing = {(c.claimId, c.resourceId): c for c in self.contradictions.values() if c.resolvedAt is None}
        for finding in result.findings:
            key = (finding.claimId, finding.resourceId)
            if finding.verdict is Verdict.SUPPORTED and key in existing and not self._cannot_show_observed(finding):
                previous = existing.pop(key)
                self.contradictions[previous.contradictionId] = previous.model_copy(
                    update={"resolvedAt": result.evaluatedAt, "resolution": ContradictionResolution.FIXED}
                )
        merged: list[Contradiction] = []
        for contradiction in result.contradictions:
            key = (contradiction.claimId, contradiction.resourceId)
            if key in existing:
                previous = existing[key]
                updated = previous.model_copy(
                    update={
                        "lastSeenAt": contradiction.lastSeenAt,
                        "observed": contradiction.observed,
                        "evidenceIds": contradiction.evidenceIds,
                    }
                )
                self.contradictions[previous.contradictionId] = updated
                merged.append(updated)
            else:
                self.contradictions[contradiction.contradictionId] = contradiction
                merged.append(contradiction)
        for proposal in result.proposals:
            self.proposals[proposal.proposalId] = proposal
        return result.model_copy(update={"contradictions": merged})

    def _cannot_show_observed(self, finding: DriftFinding) -> bool:
        """True when the ledger cannot show that the verdict rests on something observed: every record the finding
        cites is a Terraform plan (it says what Terraform would build, not what exists), or it cites a record the ledger
        does not hold. Such a finding can open a contradiction but never close one as fixed."""
        kinds = [self.evidence[i].kind for i in finding.evidenceIds if i in self.evidence]
        if len(kinds) != len(finding.evidenceIds):
            return True
        return bool(kinds) and all(kind is EvidenceKind.TF_PLAN for kind in kinds)

    def findings_for(self, decision_id: str) -> list[DriftFinding]:
        return [f for f in self.findings.values() if f.decisionId == decision_id]

    def open_contradictions(self, decision_id: str | None = None) -> list[Contradiction]:
        return [
            c
            for c in self.contradictions.values()
            if c.resolvedAt is None and (decision_id is None or c.decisionId == decision_id)
        ]

    def open_proposals(self, decision_id: str | None = None) -> list[ReviewProposal]:
        return [
            p
            for p in self.proposals.values()
            if p.status.value == "open" and (decision_id is None or p.decisionId == decision_id)
        ]

    def list_proposals(self, decision_id: str | None = None, *, status: str | None = None) -> list[ReviewProposal]:
        return [
            p
            for p in self.proposals.values()
            if (status is None or p.status.value == status) and (decision_id is None or p.decisionId == decision_id)
        ]

    def get_proposal(self, proposal_id: str) -> ReviewProposal:
        try:
            return self.proposals[proposal_id]
        except KeyError:
            raise NotFound(proposal_id) from None

    def update_proposal(self, proposal: ReviewProposal) -> ReviewProposal:
        self.get_proposal(proposal.proposalId)
        self.proposals[proposal.proposalId] = proposal
        return proposal

    def add_approval(self, approval: Approval) -> Approval:
        self.approvals[approval.approvalId] = approval
        return approval

    def approvals_for(self, proposal_id: str) -> list[Approval]:
        return [a for a in self.approvals.values() if a.proposalId == proposal_id]
