from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cloud_crawler_core.ids import new_id
from cloud_crawler_core.models import (
    Claim,
    DecisionRecord,
    DecisionScope,
    DecisionStatus,
    EvidenceRequirement,
    Expectation,
    Operator,
    Selector,
    Severity,
    SourceProvenance,
    SourceType,
)

SAMPLES = Path(__file__).resolve().parents[3] / "samples"
NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)


def make_decision(
    *,
    detector_id: str = "zone-redundancy",
    expectation: Expectation | None = None,
    selector: Selector | None = None,
    severity: Severity = Severity.CRITICAL,
    max_age_hours: int = 24,
    scope: DecisionScope | None = None,
) -> DecisionRecord:
    decision_id = new_id("decision")
    claim_id = new_id("claim")
    claim = Claim(
        claimId=claim_id,
        decisionId=decision_id,
        statement="Production data-platform resources are zone redundant",
        detectorId=detector_id,
        selector=selector
        or Selector(
            resourceTypes=[
                "microsoft.sql/servers/databases",
                "microsoft.storage/storageaccounts",
                "microsoft.dbforpostgresql/flexibleservers",
                "microsoft.documentdb/databaseaccounts",
            ],
            tagSelectors={"env": "prod"},
        ),
        severity=severity,
        expectation=expectation or Expectation(property="zoneRedundant", operator=Operator.EQ, value=True),
    )
    return DecisionRecord(
        decisionId=decision_id,
        status=DecisionStatus.ACCEPTED,
        title="Production data platform must be zone redundant",
        claims=[claim],
        scope=scope or DecisionScope(subscriptionIds=["00000000-0000-0000-0000-000000000001"]),
        evidenceRequirements=[EvidenceRequirement(claimId=claim_id, maxAgeHours=max_age_hours)],
        provenance=SourceProvenance(sourceType=SourceType.HUMAN),
        createdAt=NOW,
    )
