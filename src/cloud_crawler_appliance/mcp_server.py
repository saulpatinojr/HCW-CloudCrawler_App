"""The appliance's MCP server: the first three tools of the catalogue (website proposal, section 16).

Tool names use the `namespace_action` style Azure MCP uses in `all` mode so a client's allow-list treats both
servers alike. Every tool returns `structuredContent` (a pydantic model) and a concise text `content`, mirroring
Azure MCP's compact structured-output mode. Tool metadata carries `callsAzure: false`: the lab edition's security
suite reads the tool list over the protocol and fails if any tool says otherwise.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import mcp_types as types
from cloud_crawler_core import __version__ as engine_version
from cloud_crawler_core.drift import evaluate_decision
from cloud_crawler_core.hashing import sha256_text
from cloud_crawler_core.ids import new_id
from cloud_crawler_core.ingest import ingest
from cloud_crawler_core.ledger import InMemoryLedger, NotFound
from cloud_crawler_core.models import (
    Alternative,
    Claim,
    DecisionRecord,
    DecisionScope,
    DecisionStatus,
    DriftResult,
    EvidenceClass,
    EvidenceKind,
    EvidenceRequirement,
    Expectation,
    Selector,
    Severity,
    SourceProvenance,
    SourceType,
    Subject,
)
from cloud_crawler_core.normalize import IngestionError
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field

from cloud_crawler_appliance import __version__
from cloud_crawler_appliance.security import logging as logs

INSTRUCTIONS = (
    "Cloud Crawler keeps architecture decisions, claims and evidence, and evaluates drift deterministically. "
    "Create a decision with claims (adr_create), hand in evidence (evidence_ingest), then evaluate (drift_evaluate). "
    "Verdicts come from detectors, never from a model; unknown lowers coverage, never score. Not an audit."
)


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
    status: DecisionStatus = DecisionStatus.DRAFT
    sourceType: SourceType = SourceType.HUMAN
    actorId: str | None = Field(default=None, description="The author's object id; stored only as a sha256")


class DecisionCreated(BaseModel):
    decisionId: str
    version: int
    status: DecisionStatus
    claimIds: list[str]


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


class DriftEvaluation(BaseModel):
    result: DriftResult
    engineVersion: str


def build_mcp_server(ledger: InMemoryLedger, *, max_rows: int = 5_000) -> MCPServer:
    server = MCPServer(
        "cloud-crawler",
        title="Cloud Crawler",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://github.com/saulpatinojr/HCW-CloudCrawler_App",
    )
    meta = {"callsAzure": False, "engineVersion": engine_version}

    @server.tool(
        name="adr_create",
        title="Create a decision record",
        description="Create an architecture decision record with its claims. Returns the decision and claim ids.",
        annotations=types.ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
        ),
        meta=meta,
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
        logs.log_event("decision_created", claims=len(claims))
        return DecisionCreated(
            decisionId=decision_id, version=record.version, status=record.status, claimIds=[c.claimId for c in claims]
        )

    @server.tool(
        name="evidence_ingest",
        title="Ingest evidence",
        description=(
            "Validate, hash, redact, normalise and store an artifact or an Azure MCP result with provenance. "
            "kind arg-export takes a Resource Graph JSON export (an array, or an object with a data array) as "
            "imported evidence."
        ),
        annotations=types.ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
        meta=meta,
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
            raise ValueError(f"{exc.code}: {exc}") from None
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

    @server.tool(
        name="drift_evaluate",
        title="Evaluate drift",
        description=(
            "Run every claim's detector of one decision against the evidence in the ledger. Returns findings, open "
            "contradictions, review proposals, the severity-weighted score and the coverage."
        ),
        annotations=types.ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
        meta=meta,
    )
    def drift_evaluate(decisionId: str) -> DriftEvaluation:
        try:
            decision = ledger.get_decision(decisionId)
        except NotFound:
            raise ValueError("not_found: no such decision") from None
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

    return server
