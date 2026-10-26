"""The ingestion pipeline: validate, hash, redact, normalise, correlate, assign confidence and expiry, record
provenance.

Deterministic and the same in both editions. The raw payload is hashed before redaction so the record proves what
arrived; what is stored and shown is the redacted, normalised form. Confidence and expiry follow the evidence class
and source (website proposal, section 13.1); anything unauthenticated is capped at 0.74.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from cloud_crawler_core.hashing import sha256_of
from cloud_crawler_core.ids import new_id
from cloud_crawler_core.models import (
    Correlation,
    Evidence,
    EvidenceClass,
    EvidenceKind,
    NormalizedResource,
    Redaction,
    SourceProvenance,
    SourceType,
    Subject,
)
from cloud_crawler_core.normalize import (
    IngestionError,
    check_json_bounds,
    parse_azure_mcp_result,
    parse_resource_graph_json,
    parse_terraform_plan,
    parse_terraform_state,
)
from cloud_crawler_core.redaction import redact_payload

UNAUTHENTICATED_CAP = 0.74
REDACTION_RULES = ["denied-keys", "secret-shaped-values"]

# (class, source) -> (confidence, time to live). Imported through a pipeline carries provenance an upload lacks.
CONFIDENCE: dict[tuple[EvidenceClass, SourceType], tuple[float, timedelta]] = {
    (EvidenceClass.OBSERVED, SourceType.AZURE_MCP): (0.95, timedelta(hours=24)),
    (EvidenceClass.OBSERVED, SourceType.COLLECTOR): (0.95, timedelta(hours=24)),
    (EvidenceClass.IMPORTED, SourceType.PIPELINE): (0.90, timedelta(days=7)),
    (EvidenceClass.IMPORTED, SourceType.UPLOAD): (0.80, timedelta(days=7)),
    (EvidenceClass.DECLARED, SourceType.HUMAN): (1.0, timedelta(days=36500)),
    (EvidenceClass.INFERRED, SourceType.LLM): (0.50, timedelta(hours=24)),
}
DEFAULT_CONFIDENCE = (0.60, timedelta(hours=24))

# Which classes a kind may arrive as. An export is never "observed": it was observed by someone else, then handed in.
ALLOWED_CLASSES: dict[EvidenceKind, frozenset[EvidenceClass]] = {
    EvidenceKind.AZURE_MCP_RESULT: frozenset({EvidenceClass.OBSERVED}),
    EvidenceKind.ARG_EXPORT: frozenset({EvidenceClass.IMPORTED}),
    EvidenceKind.AZQR_REPORT: frozenset({EvidenceClass.IMPORTED}),
    EvidenceKind.TF_STATE: frozenset({EvidenceClass.IMPORTED}),
    EvidenceKind.TF_PLAN: frozenset({EvidenceClass.IMPORTED}),
    EvidenceKind.AZTFEXPORT_MAPPING: frozenset({EvidenceClass.IMPORTED}),
    EvidenceKind.COST_EXPORT: frozenset({EvidenceClass.IMPORTED}),
    EvidenceKind.WAF_GUIDE: frozenset({EvidenceClass.DECLARED}),
    EvidenceKind.CLOUD_ARCHITECT_STATE: frozenset({EvidenceClass.INFERRED}),
    EvidenceKind.CUSTOM: frozenset(
        {EvidenceClass.DECLARED, EvidenceClass.OBSERVED, EvidenceClass.IMPORTED, EvidenceClass.DERIVED}
    ),
}

# Kinds this version can normalise: Resource Graph exports and Terraform documents into resources, Azure MCP results
# into observation rows keyed by the tool named in the provenance. Every other kind (and a result of a tool this
# version does not know) is stored redacted, unparsed, for later versions.
NORMALISED_KINDS = frozenset(
    {EvidenceKind.ARG_EXPORT, EvidenceKind.TF_STATE, EvidenceKind.TF_PLAN, EvidenceKind.AZURE_MCP_RESULT}
)
# Kinds whose normalised payload is a list of resources the detectors read. A Terraform document carries a summary too.
RESOURCE_KINDS = frozenset({EvidenceKind.ARG_EXPORT, EvidenceKind.TF_STATE, EvidenceKind.TF_PLAN})
TERRAFORM_KINDS = frozenset({EvidenceKind.TF_STATE, EvidenceKind.TF_PLAN})
ARM_ID_PREFIX = "/subscriptions/"


def confidence_for(
    evidence_class: EvidenceClass, source: SourceType, *, authenticated: bool
) -> tuple[float, timedelta]:
    confidence, ttl = CONFIDENCE.get((evidence_class, source), DEFAULT_CONFIDENCE)
    if not authenticated:
        confidence = min(confidence, UNAUTHENTICATED_CAP)
    return confidence, ttl


def ingest(
    *,
    kind: EvidenceKind,
    evidence_class: EvidenceClass,
    payload: Any,
    subject: Subject,
    provenance: SourceProvenance,
    authenticated: bool,
    now: datetime | None = None,
    collection_run_id: str | None = None,
    max_rows: int = 5_000,
    ttl_override: timedelta | None = None,
) -> Evidence:
    """Build the evidence record. Raises IngestionError (with a content-free `code`) on anything it will not store."""
    now = now or datetime.now(UTC)
    if evidence_class not in ALLOWED_CLASSES[kind]:
        raise IngestionError("invalid_request", f"kind {kind.value} cannot be {evidence_class.value} evidence")
    if kind in TERRAFORM_KINDS:
        # Before anything that recurses (hashing, redaction) or copies the document.
        check_json_bounds(payload)
    payload_hash = sha256_of(payload)
    redacted, removed = redact_payload(payload)
    correlations: list[Correlation] = []
    stored: Any = redacted
    if kind is EvidenceKind.ARG_EXPORT:
        resources = parse_resource_graph_json(redacted, max_rows=max_rows)
        stored = {"resources": [r.model_dump(mode="json") for r in resources]}
        correlations = [Correlation(type="resource", value=r.id) for r in resources]
        subject = _widen_subject(subject, resources)
    elif kind in TERRAFORM_KINDS:
        # Sensitive values are withheld inside the normaliser; the stored payload is the rows and a summary, never
        # the document.
        parse = parse_terraform_state if kind is EvidenceKind.TF_STATE else parse_terraform_plan
        document = parse(redacted, max_rows=max_rows, default_subscription=subject.subscriptionId)
        stored = {"resources": [r.model_dump(mode="json") for r in document.resources], "terraform": document.summary}
        correlations = [
            Correlation(type="resource" if r.id.startswith(ARM_ID_PREFIX) else "terraform-address", value=r.id)
            for r in document.resources
        ]
        subject = _widen_subject(subject, [r for r in document.resources if r.id.startswith(ARM_ID_PREFIX)])
    elif kind is EvidenceKind.AZURE_MCP_RESULT:
        parsed = parse_azure_mcp_result(provenance.tool, redacted, max_rows=max_rows)
        if parsed is not None:
            stored = parsed
            correlations = [
                Correlation(type="resource", value=row["resourceId"]) for row in parsed["rows"] if row.get("resourceId")
            ]
    confidence, ttl = confidence_for(evidence_class, provenance.sourceType, authenticated=authenticated)
    return Evidence(
        evidenceId=new_id("evidence"),
        **{"class": evidence_class},
        kind=kind,
        subject=subject,
        payload=stored,
        payloadHash=payload_hash,
        redaction=Redaction(rules=list(REDACTION_RULES), removedCount=removed),
        provenance=provenance,
        confidence=confidence,
        retrievedAt=now,
        expiresAt=now + (ttl_override or ttl),
        collectionRunId=collection_run_id,
        correlations=correlations,
    )


def _widen_subject(subject: Subject, resources: list[NormalizedResource]) -> Subject:
    ids = list(dict.fromkeys([*subject.resourceIds, *(r.id for r in resources)]))
    subscription = subject.subscriptionId or next((r.subscriptionId for r in resources if r.subscriptionId), None)
    return Subject(scope=subject.scope, subscriptionId=subscription, resourceIds=ids)


def resources_of(evidence: Evidence) -> list[NormalizedResource]:
    """The normalised resources an evidence record carries, or none for kinds this version does not normalise."""
    if evidence.kind not in RESOURCE_KINDS or not isinstance(evidence.payload, dict):
        return []
    return [NormalizedResource.model_validate(row) for row in evidence.payload.get("resources", [])]


def observations_of(evidence: Evidence) -> tuple[str, list[dict[str, Any]]] | None:
    """`(tool, rows)` for a normalised Azure MCP result; None for anything else (unparsed results included)."""
    if evidence.kind is not EvidenceKind.AZURE_MCP_RESULT or not isinstance(evidence.payload, dict):
        return None
    tool, rows = evidence.payload.get("tool"), evidence.payload.get("rows")
    if not isinstance(tool, str) or not isinstance(rows, list):
        return None
    return tool, rows
