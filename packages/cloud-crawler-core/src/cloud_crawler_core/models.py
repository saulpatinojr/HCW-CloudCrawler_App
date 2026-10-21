"""The records the appliance is the source of truth for, and the shapes evidence takes on the way in.

Field names are the JSON names (camelCase) so a record round-trips through the MCP wire and the ledger unchanged.
Every model forbids unknown fields: a record that carries something this version does not know is an error, never
silently kept. Enumerations are string enums so they serialise as the words the documentation uses.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------------------------------------------------


class EvidenceClass(StrEnum):
    DECLARED = "declared"
    OBSERVED = "observed"
    IMPORTED = "imported"
    DERIVED = "derived"
    INFERRED = "inferred"
    PROPOSED = "proposed"


class EvidenceKind(StrEnum):
    AZURE_MCP_RESULT = "azure-mcp-result"
    ARG_EXPORT = "arg-export"
    AZQR_REPORT = "azqr-report"
    TF_STATE = "tf-state"
    TF_PLAN = "tf-plan"
    AZTFEXPORT_MAPPING = "aztfexport-mapping"
    COST_EXPORT = "cost-export"
    WAF_GUIDE = "waf-guide"
    CLOUD_ARCHITECT_STATE = "cloud-architect-state"
    CUSTOM = "custom"


class SourceType(StrEnum):
    AZURE_MCP = "azure-mcp"
    UPLOAD = "upload"
    PIPELINE = "pipeline"
    COLLECTOR = "collector"
    LLM = "llm"
    HUMAN = "human"


class IdentityMode(StrEnum):
    OBO = "obo"
    MANAGED_IDENTITY = "managed-identity"
    NONE = "none"


class ScopeKind(StrEnum):
    TENANT = "tenant"
    SUBSCRIPTION = "subscription"
    RESOURCE_GROUP = "resource-group"
    RESOURCE = "resource"
    DECISION = "decision"


class SourceProvenance(StrictModel):
    sourceType: SourceType
    tool: str | None = None
    serverName: str | None = None
    serverVersion: str | None = None
    protocolVersion: str | None = None
    parametersRedacted: dict[str, str] = Field(default_factory=dict, description="parameter name -> sha256 of value")
    identityMode: IdentityMode = IdentityMode.NONE
    actorId: str | None = Field(default=None, description="sha256 of the actor's object id; never the id itself")
    artifactName: str | None = None
    artifactHash: str | None = None
    workflowRunId: str | None = None


class Subject(StrictModel):
    scope: ScopeKind
    subscriptionId: str | None = None
    resourceIds: list[str] = Field(default_factory=list)


class Correlation(StrictModel):
    type: str
    value: str


class Redaction(StrictModel):
    rules: list[str] = Field(default_factory=list)
    removedCount: int = 0


class Evidence(StrictModel):
    evidenceId: str
    evidenceClass: EvidenceClass = Field(alias="class")
    kind: EvidenceKind
    schemaVersion: str = SCHEMA_VERSION
    subject: Subject
    payload: Any
    payloadHash: str
    redaction: Redaction = Field(default_factory=Redaction)
    provenance: SourceProvenance
    confidence: float = Field(ge=0.0, le=1.0)
    retrievedAt: datetime
    expiresAt: datetime | None = None
    collectionRunId: str | None = None
    correlations: list[Correlation] = Field(default_factory=list)


class RunSource(StrictModel):
    sourceType: SourceType
    tool: str | None = None
    status: str = "ok"
    itemCount: int = 0
    evidenceIds: list[str] = Field(default_factory=list)


class CollectionRun(StrictModel):
    runId: str
    startedAt: datetime
    finishedAt: datetime | None = None
    trigger: str = "session"
    identityMode: IdentityMode = IdentityMode.NONE
    scope: Subject
    sources: list[RunSource] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list, description="error codes only, never text")
    summary: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------------------------------------------------
# Normalised resources (the shape every detector reads)
# ---------------------------------------------------------------------------------------------------------------------


class NormalizedResource(StrictModel):
    id: str
    type: str
    name: str
    location: str | None = None
    resourceGroup: str | None = None
    subscriptionId: str | None = None
    zones: list[str] = Field(default_factory=list)
    sku: dict[str, Any] = Field(default_factory=dict)
    identity: dict[str, Any] = Field(default_factory=dict)
    tags: dict[str, str] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------------------------------------------------
# Decisions and claims
# ---------------------------------------------------------------------------------------------------------------------


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_WEIGHTS: dict[Severity, int] = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
}


class Operator(StrEnum):
    EQ = "eq"
    NEQ = "neq"
    IN = "in"
    GTE = "gte"
    LTE = "lte"
    EXISTS = "exists"
    ABSENT = "absent"
    SUBSET = "subset"
    ALL = "all"
    ANY = "any"


class Expectation(StrictModel):
    property: str
    operator: Operator
    value: Any = None


class Selector(StrictModel):
    resourceTypes: list[str] = Field(default_factory=list, description="lower-case ARM types; empty means any")
    tagSelectors: dict[str, str] = Field(default_factory=dict, description="every listed tag must match exactly")
    nameGlobs: list[str] = Field(default_factory=list)
    subscriptionIds: list[str] = Field(default_factory=list)


class Claim(StrictModel):
    claimId: str
    decisionId: str
    statement: str
    detectorId: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    selector: Selector = Field(default_factory=Selector)
    severity: Severity = Severity.HIGH
    required: bool = True
    expectation: Expectation


class CostBasis(StrEnum):
    ESTIMATED_RETAIL = "estimated-retail"
    ESTIMATED_EFFECTIVE = "estimated-effective"
    ACTUAL = "actual"
    FORECAST = "forecast"


class CostEstimate(StrictModel):
    basis: CostBasis
    currency: str = "USD"
    monthlyAmount: float = Field(ge=0.0)
    evidenceIds: list[str] = Field(default_factory=list)
    note: str | None = None


class Alternative(StrictModel):
    alternativeId: str
    title: str
    description: str = ""
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    costEstimates: list[CostEstimate] = Field(default_factory=list)
    selected: bool = False
    rejectionReason: str | None = None


class DecisionStatus(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"
    REJECTED = "rejected"


class DecisionScope(StrictModel):
    tenantId: str | None = None
    subscriptionIds: list[str] = Field(default_factory=list)
    resourceGroupNames: list[str] = Field(default_factory=list)
    tagSelectors: dict[str, str] = Field(default_factory=dict)


class EvidenceRequirement(StrictModel):
    claimId: str
    requiredClasses: list[EvidenceClass] = Field(
        default_factory=lambda: [EvidenceClass.OBSERVED, EvidenceClass.IMPORTED]
    )
    maxAgeHours: int = Field(default=24, ge=1)


class DecisionRecord(StrictModel):
    decisionId: str
    version: int = 1
    status: DecisionStatus = DecisionStatus.DRAFT
    title: str
    context: str = ""
    decisionDrivers: list[str] = Field(default_factory=list)
    decision: str = ""
    consequences: list[str] = Field(default_factory=list)
    openQuestions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    scope: DecisionScope = Field(default_factory=DecisionScope)
    evidenceRequirements: list[EvidenceRequirement] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)
    supersededBy: str | None = None
    relatedDecisions: list[str] = Field(default_factory=list)
    provenance: SourceProvenance
    createdBy: str | None = Field(default=None, description="sha256 of the author's object id")
    createdAt: datetime
    acceptedBy: str | None = None
    acceptedAt: datetime | None = None


# ---------------------------------------------------------------------------------------------------------------------
# Drift, contradictions, reviews
# ---------------------------------------------------------------------------------------------------------------------


class Verdict(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not-applicable"


class DriftFinding(StrictModel):
    findingId: str
    claimId: str
    decisionId: str
    resourceId: str | None = None
    verdict: Verdict
    observed: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    evidenceIds: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    unknownReason: str | None = None
    detectorId: str
    detectorVersion: str
    evaluatedAt: datetime


class ContradictionResolution(StrEnum):
    FIXED = "fixed"
    DECISION_CHANGED = "decision-changed"
    ACCEPTED_RISK = "accepted-risk"
    FALSE_POSITIVE = "false-positive"


class Contradiction(StrictModel):
    contradictionId: str
    claimId: str
    decisionId: str
    resourceId: str | None = None
    evidenceIds: list[str] = Field(default_factory=list)
    observed: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    firstSeenAt: datetime
    lastSeenAt: datetime
    resolvedAt: datetime | None = None
    resolution: ContradictionResolution | None = None


class ProposalKind(StrEnum):
    RETIREMENT = "retirement"
    CONTRADICTION = "contradiction"
    ADVISOR = "advisor"
    COST = "cost"
    EXPIRY = "expiry"
    SUPERSESSION = "supersession"


class ProposalStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class RecommendedAction(StrictModel):
    action: str
    source: str = "catalog"
    effort: str | None = None
    destructive: bool = False


class ReviewProposal(StrictModel):
    proposalId: str
    kind: ProposalKind
    decisionId: str | None = None
    claimIds: list[str] = Field(default_factory=list)
    evidenceIds: list[str] = Field(default_factory=list)
    impactedResourceIds: list[str] = Field(default_factory=list)
    title: str
    rationale: str = ""
    migrationConsiderations: list[str] = Field(default_factory=list)
    recommendedActions: list[RecommendedAction] = Field(default_factory=list)
    dueBy: datetime | None = None
    status: ProposalStatus = ProposalStatus.OPEN
    createdAt: datetime


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class Approval(StrictModel):
    approvalId: str
    proposalId: str
    decision: ApprovalDecision
    comment: str = ""
    actorId: str = Field(description="sha256 of the actor's object id")
    actorRole: str = "architect"
    at: datetime
    evidenceSnapshotHash: str


class DriftSummary(StrictModel):
    supported: int = 0
    contradicted: int = 0
    unknown: int = 0
    notApplicable: int = 0
    score: float | None = Field(
        default=None, description="severity-weighted supported / observed, 0-100; None when nothing observed"
    )
    coverage: float | None = Field(
        default=None, description="observed / (observed + unknown), 0-1; None when nothing evaluated"
    )


class DriftResult(StrictModel):
    decisionId: str
    evaluatedAt: datetime
    findings: list[DriftFinding] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    proposals: list[ReviewProposal] = Field(default_factory=list)
    summary: DriftSummary = Field(default_factory=DriftSummary)
