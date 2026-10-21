"""What a detector is: a pure function from (claim, resources) to findings, with the three-valued logic every
detector shares. A detector reads one property per resource type and reports `True`, `False` or `None` (cannot be
told from this evidence). The base turns that into `supported`, `contradicted` or `unknown`; resources outside the
claim's selector are `not-applicable`. No detector ever returns `contradicted` from `None`."""

from __future__ import annotations

import fnmatch
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cloud_crawler_core.ids import new_id
from cloud_crawler_core.models import Claim, DriftFinding, NormalizedResource, Operator, Selector, Verdict


@dataclass(frozen=True)
class Reading:
    """One resource's answer to the detector's question. `value` is what was observed, for the finding."""

    answer: bool | None
    value: Any = None
    reason: str | None = None  # when answer is None: why the evidence cannot say


Reader = Callable[[NormalizedResource, dict[str, Any]], Reading]


def selector_matches(selector: Selector, resource: NormalizedResource) -> bool:
    if selector.resourceTypes and resource.type not in {t.lower() for t in selector.resourceTypes}:
        return False
    if selector.subscriptionIds and (resource.subscriptionId or "") not in {
        s.lower() for s in selector.subscriptionIds
    }:
        return False
    for key, expected in selector.tagSelectors.items():
        if resource.tags.get(key) != expected:
            return False
    return not selector.nameGlobs or any(fnmatch.fnmatchcase(resource.name, glob) for glob in selector.nameGlobs)


@dataclass(frozen=True)
class Detector:
    detector_id: str
    version: str
    question: str
    readers: dict[str, Reader] = field(default_factory=dict)  # lower-case ARM type -> reader

    @property
    def resource_types(self) -> tuple[str, ...]:
        return tuple(sorted(self.readers))

    def evaluate(
        self,
        claim: Claim,
        resources: Iterable[NormalizedResource],
        *,
        evidence_ids: list[str],
        now: datetime,
    ) -> list[DriftFinding]:
        expected_true = _expected_boolean(claim)
        findings: list[DriftFinding] = []
        for resource in resources:
            reader = self.readers.get(resource.type)
            if reader is None or not selector_matches(claim.selector, resource):
                findings.append(self._finding(claim, resource, Verdict.NOT_APPLICABLE, {}, evidence_ids, now))
                continue
            reading = reader(resource, claim.parameters)
            # the answer under the claimed property, plus the raw reading it came from (a SKU name, a list of zones)
            observed = {claim.expectation.property: reading.answer, "reading": reading.value}
            if reading.answer is None:
                finding = self._finding(claim, resource, Verdict.UNKNOWN, observed, evidence_ids, now)
                finding.unknownReason = reading.reason or "the evidence does not carry this property"
                findings.append(finding)
                continue
            verdict = Verdict.SUPPORTED if reading.answer == expected_true else Verdict.CONTRADICTED
            findings.append(self._finding(claim, resource, verdict, observed, evidence_ids, now))
        return findings

    def _finding(
        self,
        claim: Claim,
        resource: NormalizedResource,
        verdict: Verdict,
        observed: dict[str, Any],
        evidence_ids: list[str],
        now: datetime,
    ) -> DriftFinding:
        return DriftFinding(
            findingId=new_id("finding"),
            claimId=claim.claimId,
            decisionId=claim.decisionId,
            resourceId=resource.id,
            verdict=verdict,
            observed=observed,
            expected={claim.expectation.property: claim.expectation.value},
            evidenceIds=list(evidence_ids),
            detectorId=self.detector_id,
            detectorVersion=self.version,
            evaluatedAt=now,
        )


def _expected_boolean(claim: Claim) -> bool:
    """Boolean detectors accept `eq true`, `eq false` and `neq` of either; anything else is a claim authoring error."""
    expectation = claim.expectation
    if expectation.operator not in (Operator.EQ, Operator.NEQ) or not isinstance(expectation.value, bool):
        raise ValueError(
            f"claim {claim.claimId}: detector {claim.detectorId} takes expectation eq/neq true|false, "
            f"got {expectation.operator.value} {expectation.value!r}"
        )
    return expectation.value if expectation.operator is Operator.EQ else not expectation.value
