"""The appliance's MCP server: the tool catalogue of the website proposal, section 16, minus the Full-only tools.

Tool names use the `namespace_action` style Azure MCP uses in `all` mode so a client's allow-list treats both
servers alike. Every tool returns `structuredContent` (a pydantic model) and a concise text `content`, mirroring
Azure MCP's compact structured-output mode. Tool metadata carries `callsAzure: false` (the lab edition's security
suite reads the tool list over the protocol and fails if any tool says otherwise) and `caller`, the caller class.
Every refusal is a `ToolError` whose text starts with a content-free code (`not_found`, `invalid_request`,
`invalid_state`, or an ingestion code) so the caller gets the code and the log gets only the code:

- `model`: tools a chat model may call. Reads, drafts, evidence and proposals. `adr_create` creates `draft` or
  `proposed` decisions only.
- `human`: tools that change an authoritative record and need a person's explicit action (`adr_accept`,
  `review_decide`, and the Full-only `collection_run_azure`). They take the actor's object id and store only its
  hash. The website keeps them out of the model's tool list and calls them from its own authenticated routes; this
  server records who acted, never why.

`collection_run_azure` is the one tool with `meta.callsAzure: true`: it drives the Azure MCP host through the
standard read-only sequence and ingests every result. It exists only when a host is configured (`CC_AZMCP_MODE`),
so the lab edition, which never has one, never lists it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

import mcp_types as types
from cloud_crawler_core import __version__ as engine_version
from cloud_crawler_core.drift import evaluate_decision
from cloud_crawler_core.hashing import sha256_of, sha256_text
from cloud_crawler_core.ids import new_id
from cloud_crawler_core.ingest import ingest
from cloud_crawler_core.ledger import InMemoryLedger, NotFound
from cloud_crawler_core.models import (
    Alternative,
    Approval,
    ApprovalDecision,
    Claim,
    CollectionRun,
    Contradiction,
    DecisionRecord,
    DecisionScope,
    DecisionStatus,
    DriftFinding,
    DriftResult,
    Evidence,
    EvidenceClass,
    EvidenceKind,
    EvidenceRequirement,
    Expectation,
    ProposalKind,
    ProposalStatus,
    RecommendedAction,
    ReviewProposal,
    Selector,
    Severity,
    SourceProvenance,
    SourceType,
    Subject,
    Verdict,
)
from cloud_crawler_core.normalize import IngestionError
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field

from cloud_crawler_appliance import __version__
from cloud_crawler_appliance.mcp_host import AzureMcpHost, HostError, collect
from cloud_crawler_appliance.security import logging as logs

INSTRUCTIONS = (
    "Cloud Crawler keeps architecture decisions, claims and evidence, and evaluates drift deterministically. "
    "Create a decision with claims (adr_create), hand in evidence (evidence_ingest), then evaluate (drift_evaluate); "
    "browse with evidence_list, drift_list, contradiction_list and review_list. Verdicts come from detectors, never "
    "from a model; unknown lowers coverage, never score. adr_accept and review_decide need a person. Not an audit."
)

MAX_LIMIT = 200
Caller = Literal["model", "human"]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimInput(StrictInput):
    statement: str = Field(description="The claim in the architect's words")
    detectorId: str = Field(description="A registered detector id, for example zone-redundancy")
    expectation: Expectation
    parameters: dict[str, Any] = Field(default_factory=dict)
    selector: Selector = Field(default_factory=Selector)
    severity: Severity = Severity.HIGH
    required: bool = True
    maxAgeHours: int = Field(default=24, ge=1)


class DecisionInput(StrictInput):
    title: str
    context: str = ""
    decision: str = ""
    decisionDrivers: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    openQuestions: list[str] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)
    claims: list[ClaimInput] = Field(default_factory=list)
    scope: DecisionScope = Field(default_factory=DecisionScope)
    status: Literal[DecisionStatus.DRAFT, DecisionStatus.PROPOSED] = Field(
        default=DecisionStatus.DRAFT, description="draft or proposed; adr_accept (a person) makes it accepted"
    )
    sourceType: SourceType = SourceType.HUMAN
    actorId: str | None = Field(default=None, description="The author's object id; stored only as a sha256")


class DecisionCreated(BaseModel):
    decisionId: str
    version: int
    status: DecisionStatus
    claimIds: list[str]


class DecisionAccepted(BaseModel):
    decisionId: str
    version: int
    status: DecisionStatus
    acceptedBy: str
    acceptedAt: datetime


class DecisionSummary(BaseModel):
    decisionId: str
    title: str
    status: DecisionStatus
    version: int
    claimCount: int
    createdAt: datetime
    acceptedAt: datetime | None


class DecisionList(BaseModel):
    decisions: list[DecisionSummary]
    total: int


class EvidenceIngested(BaseModel):
    evidenceId: str
    evidenceClass: EvidenceClass
    kind: EvidenceKind
    payloadHash: str
    resourceCount: int
    redactedCount: int
    confidence: float
    retrievedAt: datetime
    expiresAt: datetime | None


class EvidenceSummary(BaseModel):
    """Everything about a record but its payload: what a table on the lab page shows."""

    evidenceId: str
    evidenceClass: EvidenceClass
    kind: EvidenceKind
    sourceType: SourceType
    tool: str | None
    subjectScope: str
    subscriptionId: str | None
    resourceCount: int
    payloadHash: str
    redactedCount: int
    confidence: float
    retrievedAt: datetime
    expiresAt: datetime | None
    collectionRunId: str | None


class EvidenceList(BaseModel):
    evidence: list[EvidenceSummary]
    total: int


class EvidenceRecord(BaseModel):
    evidence: Evidence


class DriftEvaluation(BaseModel):
    result: DriftResult
    engineVersion: str


class FindingList(BaseModel):
    findings: list[DriftFinding]
    total: int


class ContradictionList(BaseModel):
    contradictions: list[Contradiction]
    total: int


class ProposalList(BaseModel):
    proposals: list[ReviewProposal]
    total: int


class ProposalRecord(BaseModel):
    proposal: ReviewProposal
    approvals: list[Approval]


class Decided(BaseModel):
    proposalId: str
    status: ProposalStatus
    approval: Approval


class ProposalInput(StrictInput):
    kind: ProposalKind
    title: str
    rationale: str = ""
    decisionId: str | None = None
    claimIds: list[str] = Field(default_factory=list)
    evidenceIds: list[str] = Field(default_factory=list)
    impactedResourceIds: list[str] = Field(default_factory=list)
    migrationConsiderations: list[str] = Field(default_factory=list)
    recommendedActions: list[RecommendedAction] = Field(default_factory=list)
    dueBy: datetime | None = None


class ProposalCreated(BaseModel):
    proposalId: str
    kind: ProposalKind
    status: ProposalStatus


class CollectionRunResult(BaseModel):
    run: CollectionRun
    azureConnectivity: str


def _annotations(*, read_only: bool, idempotent: bool) -> types.ToolAnnotations:
    return types.ToolAnnotations(
        readOnlyHint=read_only, destructiveHint=False, idempotentHint=idempotent, openWorldHint=False
    )


def _page(items: list, limit: int) -> list:
    return items[: max(1, min(limit, MAX_LIMIT))]


def _actor(actor_id: str) -> str:
    if not actor_id or not actor_id.strip():
        raise ToolError("invalid_request: actorId is required for a human-class tool")
    return sha256_text(actor_id.strip())


def build_mcp_server(ledger: InMemoryLedger, *, max_rows: int = 5_000, host: AzureMcpHost | None = None) -> MCPServer:
    server = MCPServer(
        "cloud-crawler",
        title="Cloud Crawler",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://github.com/saulpatinojr/HCW-CloudCrawler_App",
    )

    def meta(caller: Caller, *, calls_azure: bool = False) -> dict[str, Any]:
        return {"callsAzure": calls_azure, "engineVersion": engine_version, "caller": caller}

    def tool(
        name: str,
        title: str,
        description: str,
        *,
        caller: Caller,
        read_only: bool,
        idempotent: bool,
        calls_azure: bool = False,
    ):
        return server.tool(
            name=name,
            title=title,
            description=description,
            annotations=_annotations(read_only=read_only, idempotent=idempotent),
            meta=meta(caller, calls_azure=calls_azure),
        )

    def decision_or_error(decision_id: str) -> DecisionRecord:
        try:
            return ledger.get_decision(decision_id)
        except NotFound:
            raise ToolError("not_found: no such decision") from None

    # ----------------------------------------------------------------------------------------------- decisions

    @tool(
        "adr_create",
        "Create a decision record",
        "Create an architecture decision record with its claims, as a draft (or proposed). Returns the decision and "
        "claim ids. Acceptance is a separate, human step (adr_accept).",
        caller="model",
        read_only=False,
        idempotent=False,
    )
    def adr_create(decision: DecisionInput) -> DecisionCreated:
        now = datetime.now(UTC)
        decision_id = new_id("decision")
        claims: list[Claim] = []
        requirements: list[EvidenceRequirement] = []
        for item in decision.claims:
            claim_id = new_id("claim")
            claims.append(
                Claim(
                    claimId=claim_id,
                    decisionId=decision_id,
                    statement=item.statement,
                    detectorId=item.detectorId,
                    parameters=item.parameters,
                    selector=item.selector,
                    severity=item.severity,
                    required=item.required,
                    expectation=item.expectation,
                )
            )
            requirements.append(EvidenceRequirement(claimId=claim_id, maxAgeHours=item.maxAgeHours))
        record = DecisionRecord(
            decisionId=decision_id,
            status=decision.status,
            title=decision.title,
            context=decision.context,
            decisionDrivers=decision.decisionDrivers,
            decision=decision.decision,
            consequences=decision.consequences,
            openQuestions=decision.openQuestions,
            constraints=decision.constraints,
            assumptions=decision.assumptions,
            risks=decision.risks,
            alternatives=decision.alternatives,
            claims=claims,
            scope=decision.scope,
            evidenceRequirements=requirements,
            provenance=SourceProvenance(sourceType=decision.sourceType),
            createdBy=sha256_text(decision.actorId) if decision.actorId else None,
            createdAt=now,
        )
        ledger.add_decision(record)
        logs.log_event("decision_created", claims=len(claims), status=record.status.value)
        return DecisionCreated(
            decisionId=decision_id, version=record.version, status=record.status, claimIds=[c.claimId for c in claims]
        )

    @tool(
        "adr_accept",
        "Accept a decision record",
        "Mark a draft or proposed decision as accepted on behalf of a person. actorId is the person's object id and "
        "is stored only as a hash. Accepting an accepted decision again changes nothing.",
        caller="human",
        read_only=False,
        idempotent=True,
    )
    def adr_accept(decisionId: str, actorId: str, comment: str = "") -> DecisionAccepted:
        actor = _actor(actorId)
        record = decision_or_error(decisionId)
        if record.status is DecisionStatus.ACCEPTED:
            assert record.acceptedBy is not None and record.acceptedAt is not None  # by construction below
            return DecisionAccepted(
                decisionId=record.decisionId,
                version=record.version,
                status=record.status,
                acceptedBy=record.acceptedBy,
                acceptedAt=record.acceptedAt,
            )
        if record.status not in (DecisionStatus.DRAFT, DecisionStatus.PROPOSED):
            raise ToolError(f"invalid_state: a {record.status.value} decision cannot be accepted")
        now = datetime.now(UTC)
        updated = record.model_copy(
            update={
                "status": DecisionStatus.ACCEPTED,
                "version": record.version + 1,
                "acceptedBy": actor,
                "acceptedAt": now,
            }
        )
        ledger.update_decision(updated)
        logs.log_event("decision_accepted", version=updated.version, commented=bool(comment))
        return DecisionAccepted(
            decisionId=updated.decisionId,
            version=updated.version,
            status=updated.status,
            acceptedBy=actor,
            acceptedAt=now,
        )

    @tool(
        "adr_get",
        "Read a decision record",
        "Return one decision record with its claims, scope and evidence requirements.",
        caller="model",
        read_only=True,
        idempotent=True,
    )
    def adr_get(decisionId: str) -> DecisionRecord:
        return decision_or_error(decisionId)

    @tool(
        "adr_list",
        "List decision records",
        "List decision records (id, title, status, version, claim count), optionally by status, newest first.",
        caller="model",
        read_only=True,
        idempotent=True,
    )
    def adr_list(status: DecisionStatus | None = None, limit: int = 50) -> DecisionList:
        records = sorted(ledger.list_decisions(status=status.value if status else None), key=lambda d: d.createdAt)
        records.reverse()
        return DecisionList(
            decisions=[
                DecisionSummary(
                    decisionId=d.decisionId,
                    title=d.title,
                    status=d.status,
                    version=d.version,
                    claimCount=len(d.claims),
                    createdAt=d.createdAt,
                    acceptedAt=d.acceptedAt,
                )
                for d in _page(records, limit)
            ],
            total=len(records),
        )

    # ------------------------------------------------------------------------------------------------ evidence

    @tool(
        "evidence_ingest",
        "Ingest evidence",
        "Validate, hash, redact, normalise and store an artifact or an Azure MCP result with provenance. "
        "kind arg-export takes a Resource Graph JSON export (an array, or an object with a data array) as "
        "imported evidence.",
        caller="model",
        read_only=False,
        idempotent=True,
    )
    def evidence_ingest(
        kind: EvidenceKind,
        evidenceClass: EvidenceClass,
        payload: Any,
        subject: Subject,
        provenance: SourceProvenance,
        authenticated: bool = False,
    ) -> EvidenceIngested:
        try:
            record = ingest(
                kind=kind,
                evidence_class=evidenceClass,
                payload=payload,
                subject=subject,
                provenance=provenance,
                authenticated=authenticated,
                max_rows=max_rows,
            )
        except IngestionError as exc:
            logs.log_event("evidence_rejected", code=exc.code, kind=kind.value)
            raise ToolError(f"{exc.code}: {exc}") from None
        ledger.add_evidence(record)
        resource_count = len(record.correlations)
        logs.log_event(
            "evidence_ingested", kind=kind.value, resources=resource_count, redacted=record.redaction.removedCount
        )
        return EvidenceIngested(
            evidenceId=record.evidenceId,
            evidenceClass=record.evidenceClass,
            kind=record.kind,
            payloadHash=record.payloadHash,
            resourceCount=resource_count,
            redactedCount=record.redaction.removedCount,
            confidence=record.confidence,
            retrievedAt=record.retrievedAt,
            expiresAt=record.expiresAt,
        )

    @tool(
        "evidence_list",
        "List evidence",
        "List evidence records without their payloads: class, kind, source, subject, resource count, hash, "
        "confidence, retrieval and expiry; optionally by kind or class; newest first.",
        caller="model",
        read_only=True,
        idempotent=True,
    )
    def evidence_list(
        kind: EvidenceKind | None = None, evidenceClass: EvidenceClass | None = None, limit: int = 50
    ) -> EvidenceList:
        records = sorted(
            ledger.list_evidence(
                kind=kind.value if kind else None, evidence_class=evidenceClass.value if evidenceClass else None
            ),
            key=lambda e: e.retrievedAt,
            reverse=True,
        )
        return EvidenceList(
            evidence=[
                EvidenceSummary(
                    evidenceId=e.evidenceId,
                    evidenceClass=e.evidenceClass,
                    kind=e.kind,
                    sourceType=e.provenance.sourceType,
                    tool=e.provenance.tool,
                    subjectScope=e.subject.scope.value,
                    subscriptionId=e.subject.subscriptionId,
                    resourceCount=len(e.correlations),
                    payloadHash=e.payloadHash,
                    redactedCount=e.redaction.removedCount,
                    confidence=e.confidence,
                    retrievedAt=e.retrievedAt,
                    expiresAt=e.expiresAt,
                    collectionRunId=e.collectionRunId,
                )
                for e in _page(records, limit)
            ],
            total=len(records),
        )

    @tool(
        "evidence_get",
        "Read an evidence record",
        "Return one evidence record with its redacted, normalised payload and provenance.",
        caller="model",
        read_only=True,
        idempotent=True,
    )
    def evidence_get(evidenceId: str) -> EvidenceRecord:
        try:
            return EvidenceRecord(evidence=ledger.get_evidence(evidenceId))
        except NotFound:
            raise ToolError("not_found: no such evidence") from None

    # --------------------------------------------------------------------------------------------------- drift

    @tool(
        "drift_evaluate",
        "Evaluate drift",
        "Run every claim's detector of one decision against the evidence in the ledger. Returns findings, open "
        "contradictions, review proposals, the severity-weighted score and the coverage.",
        caller="model",
        read_only=False,
        idempotent=True,
    )
    def drift_evaluate(decisionId: str) -> DriftEvaluation:
        decision = decision_or_error(decisionId)
        now = datetime.now(UTC)
        result = ledger.record(evaluate_decision(decision, ledger.evidence_for(decision, now=now), now=now))
        logs.log_event(
            "drift_evaluated",
            findings=len(result.findings),
            contradicted=result.summary.contradicted,
            unknown=result.summary.unknown,
            proposals=len(result.proposals),
        )
        return DriftEvaluation(result=result, engineVersion=engine_version)

    @tool(
        "drift_list",
        "List drift findings",
        "List the findings recorded for one decision, optionally by verdict (supported, contradicted, unknown, "
        "not-applicable), newest evaluation first.",
        caller="model",
        read_only=True,
        idempotent=True,
    )
    def drift_list(decisionId: str, verdict: Verdict | None = None, limit: int = 50) -> FindingList:
        decision_or_error(decisionId)
        findings = [f for f in ledger.findings_for(decisionId) if verdict is None or f.verdict is verdict]
        findings.sort(key=lambda f: f.evaluatedAt, reverse=True)
        return FindingList(findings=_page(findings, limit), total=len(findings))

    @tool(
        "contradiction_list",
        "List open contradictions",
        "List the open contradictions, for one decision or for every decision in the ledger.",
        caller="model",
        read_only=True,
        idempotent=True,
    )
    def contradiction_list(decisionId: str | None = None, limit: int = 50) -> ContradictionList:
        if decisionId is not None:
            decision_or_error(decisionId)
        items = sorted(ledger.open_contradictions(decisionId), key=lambda c: c.firstSeenAt)
        return ContradictionList(contradictions=_page(items, limit), total=len(items))

    # -------------------------------------------------------------------------------------------------- reviews

    @tool(
        "review_list",
        "List review proposals",
        "List review proposals, for one decision or all, by status (default open): what the architects are asked "
        "to decide.",
        caller="model",
        read_only=True,
        idempotent=True,
    )
    def review_list(
        decisionId: str | None = None, status: ProposalStatus | None = ProposalStatus.OPEN, limit: int = 50
    ) -> ProposalList:
        if decisionId is not None:
            decision_or_error(decisionId)
        items = sorted(
            ledger.list_proposals(decisionId, status=status.value if status else None), key=lambda p: p.createdAt
        )
        return ProposalList(proposals=_page(items, limit), total=len(items))

    @tool(
        "review_get",
        "Read a review proposal",
        "Return one review proposal with its approval trail.",
        caller="model",
        read_only=True,
        idempotent=True,
    )
    def review_get(proposalId: str) -> ProposalRecord:
        try:
            proposal = ledger.get_proposal(proposalId)
        except NotFound:
            raise ToolError("not_found: no such proposal") from None
        return ProposalRecord(proposal=proposal, approvals=ledger.approvals_for(proposalId))

    @tool(
        "review_propose",
        "Propose a review",
        "Open a review proposal (retirement, contradiction, advisor, cost, expiry or supersession) for the architects "
        "to decide: what is impacted, why, the recommended actions and the migration considerations. The drift engine "
        "opens contradiction and retirement proposals itself; this tool is for what a collector or a model noticed.",
        caller="model",
        read_only=False,
        idempotent=False,
    )
    def review_propose(proposal: ProposalInput) -> ProposalCreated:
        if proposal.decisionId is not None:
            decision_or_error(proposal.decisionId)
        for evidence_id in proposal.evidenceIds:
            try:
                ledger.get_evidence(evidence_id)
            except NotFound:
                raise ToolError("not_found: no such evidence") from None
        record = ReviewProposal(
            proposalId=new_id("proposal"),
            kind=proposal.kind,
            decisionId=proposal.decisionId,
            claimIds=proposal.claimIds,
            evidenceIds=proposal.evidenceIds,
            impactedResourceIds=proposal.impactedResourceIds,
            title=proposal.title,
            rationale=proposal.rationale,
            migrationConsiderations=proposal.migrationConsiderations,
            recommendedActions=proposal.recommendedActions,
            dueBy=proposal.dueBy,
            createdAt=datetime.now(UTC),
        )
        ledger.proposals[record.proposalId] = record
        logs.log_event("proposal_created", kind=record.kind.value, resources=len(record.impactedResourceIds))
        return ProposalCreated(proposalId=record.proposalId, kind=record.kind, status=record.status)

    @tool(
        "review_decide",
        "Decide a review proposal",
        "Approve or reject an open review proposal on behalf of a person. actorId is the person's object id and is "
        "stored only as a hash; the approval records the hash of the evidence the proposal rested on.",
        caller="human",
        read_only=False,
        idempotent=False,
    )
    def review_decide(
        proposalId: str, decision: ApprovalDecision, actorId: str, comment: str = "", actorRole: str = "architect"
    ) -> Decided:
        actor = _actor(actorId)
        try:
            proposal = ledger.get_proposal(proposalId)
        except NotFound:
            raise ToolError("not_found: no such proposal") from None
        if proposal.status is not ProposalStatus.OPEN:
            raise ToolError(f"invalid_state: the proposal is {proposal.status.value}, not open")
        now = datetime.now(UTC)
        hashes = []
        for evidence_id in proposal.evidenceIds:
            try:
                hashes.append(ledger.get_evidence(evidence_id).payloadHash)
            except NotFound:
                hashes.append("missing")
        approval = Approval(
            approvalId=new_id("approval"),
            proposalId=proposalId,
            decision=decision,
            comment=comment,
            actorId=actor,
            actorRole=actorRole,
            at=now,
            evidenceSnapshotHash=sha256_of(sorted(hashes)),
        )
        ledger.add_approval(approval)
        status = ProposalStatus.APPROVED if decision is ApprovalDecision.APPROVE else ProposalStatus.REJECTED
        updated = ledger.update_proposal(proposal.model_copy(update={"status": status}))
        logs.log_event("review_decided", decision=decision.value, kind=proposal.kind.value, commented=bool(comment))
        return Decided(proposalId=proposalId, status=updated.status, approval=approval)

    # ------------------------------------------------------------------------------------ collection (Full only)

    if host is not None:

        @tool(
            "collection_run_azure",
            "Collect from Azure through Azure MCP",
            "Drive the Azure MCP host through the standard read-only sequence (subscriptions, resource groups, open "
            "high-impact reliability recommendations, service retirements within 180 days, policy assignments) for "
            "one subscription and ingest every result as observed evidence under one collection run. An operator's "
            "act: actorId is the person's object id, stored only as a hash. Every Azure call is read-only.",
            caller="human",
            read_only=False,
            idempotent=False,
            calls_azure=True,
        )
        async def collection_run_azure(subscriptionId: str, actorId: str) -> CollectionRunResult:
            actor = _actor(actorId)
            if not subscriptionId.strip():
                raise ToolError("invalid_request: subscriptionId is required")
            try:
                async with host:
                    run = await collect(
                        host, ledger, subscription_id=subscriptionId.strip(), actor_hash=actor, max_rows=max_rows
                    )
            except HostError as exc:
                logs.log_event("collection_run", status=exc.code)
                raise ToolError(f"{exc.code}: the host refused the run") from None
            logs.log_event(
                "collection_run",
                evidence=run.summary.get("evidence", 0),
                rows=run.summary.get("rows", 0),
                errors=len(run.errors),
                mode=host.mode,
            )
            return CollectionRunResult(run=run, azureConnectivity=host.mode)

    return server
