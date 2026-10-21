"""What a detector is: a pure function from (claim, resources) to findings, with the three-valued logic every
detector shares. A detector reads one property per resource type and reports `True`, `False` or `None` (cannot be
told from this evidence). The base turns that into `supported`, `contradicted` or `unknown`; resources outside the
claim's selector are `not-applicable`. No detector ever returns `contradicted` from `None`.

Two kinds of detector share the base. A *boolean* detector answers a yes/no question (`Reading.answer`) and the
claim's expectation is `eq`/`neq` `true`/`false`. A *valued* detector reads a value (`Reading.value`, with
`Reading.answer` `True` meaning "readable") and the claim's expectation compares it: `eq`, `neq`, `in`, `exists`,
`absent`, `gte`, `lte`. A reader registered under `"*"` applies to every resource type."""

from __future__ import annotations

import fnmatch
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cloud_crawler_core.ids import new_id
from cloud_crawler_core.models import (
    Claim,
    DecisionScope,
    DriftFinding,
    Evidence,
    Expectation,
    NormalizedResource,
    Operator,
    Selector,
    Verdict,
)


@dataclass(frozen=True)
class Reading:
    """One resource's answer to the detector's question. `value` is what was observed, for the finding. For a valued
    detector `answer` is `True` when the value could be read (the value itself may be `None`, as in "no such tag")."""

    answer: bool | None
    value: Any = None
    reason: str | None = None  # when answer is None: why the evidence cannot say


ANY_TYPE = "*"
VALUED_OPERATORS = frozenset(
    {Operator.EQ, Operator.NEQ, Operator.IN, Operator.EXISTS, Operator.ABSENT, Operator.GTE, Operator.LTE}
)


Reader = Callable[[NormalizedResource, dict[str, Any]], Reading]


def tag_of(resource: NormalizedResource, name: str) -> str | None:
    """The value of a tag by name, matched case-insensitively because Azure tag names are (values are not)."""
    wanted = name.lower()
    return next((value for key, value in resource.tags.items() if key.lower() == wanted), None)


def selector_matches(selector: Selector, resource: NormalizedResource) -> bool:
    if selector.resourceTypes and resource.type not in {t.lower() for t in selector.resourceTypes}:
        return False
    if selector.subscriptionIds and (resource.subscriptionId or "") not in {
        s.lower() for s in selector.subscriptionIds
    }:
        return False
    for key, expected in selector.tagSelectors.items():
        if tag_of(resource, key) != expected:
            return False
    return not selector.nameGlobs or any(fnmatch.fnmatchcase(resource.name, glob) for glob in selector.nameGlobs)


@dataclass(frozen=True)
class Detector:
    detector_id: str
    version: str
    question: str
    readers: dict[str, Reader] = field(default_factory=dict)  # lower-case ARM type (or "*") -> reader
    valued: bool = False  # False: boolean question; True: the reading is a value the expectation compares

    @property
    def resource_types(self) -> tuple[str, ...]:
        return tuple(sorted(self.readers))

    def reader_for(self, resource_type: str) -> Reader | None:
        return self.readers.get(resource_type) or self.readers.get(ANY_TYPE)

    def evaluate(
        self,
        claim: Claim,
        resources: Iterable[NormalizedResource],
        *,
        evidence_ids: list[str],
        now: datetime,
    ) -> list[DriftFinding]:
        expected_true = None if self.valued else _expected_boolean(claim)
        if self.valued:
            _check_valued_expectation(claim)
        findings: list[DriftFinding] = []
        for resource in resources:
            reader = self.reader_for(resource.type)
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
            if self.valued:
                observed = {claim.expectation.property: reading.value, "reading": reading.value}
                holds = compare(claim.expectation, reading.value)
            else:
                holds = reading.answer == expected_true
            verdict = Verdict.SUPPORTED if holds else Verdict.CONTRADICTED
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


def _check_valued_expectation(claim: Claim) -> None:
    expectation = claim.expectation
    if expectation.operator not in VALUED_OPERATORS:
        raise ValueError(
            f"claim {claim.claimId}: detector {claim.detectorId} takes expectation "
            f"{'/'.join(sorted(o.value for o in VALUED_OPERATORS))}, got {expectation.operator.value}"
        )
    if expectation.operator is Operator.IN and not isinstance(expectation.value, list):
        raise ValueError(f"claim {claim.claimId}: operator in takes a list, got {expectation.value!r}")
    if expectation.operator in (Operator.GTE, Operator.LTE) and not isinstance(expectation.value, int | float):
        raise ValueError(f"claim {claim.claimId}: operator {expectation.operator.value} takes a number")


def fold(value: Any) -> Any:
    """Strings compare case-insensitively and ignore spaces, because Azure does (`East US 2` is `eastus2`, a tag
    name's case is not significant, SKU names mix cases across exports)."""
    return value.replace(" ", "").lower() if isinstance(value, str) else value


def compare(expectation: Expectation, value: Any) -> bool:
    """Does the observed value satisfy the expectation? `exists`/`absent` test for a value at all; the rest compare
    folded values. A `None` value fails every comparison except `absent` and `neq`."""
    operator = expectation.operator
    if operator is Operator.EXISTS:
        return value is not None
    if operator is Operator.ABSENT:
        return value is None
    if operator is Operator.EQ:
        return fold(value) == fold(expectation.value)
    if operator is Operator.NEQ:
        return fold(value) != fold(expectation.value)
    if operator is Operator.IN:
        return value is not None and fold(value) in {fold(v) for v in expectation.value}
    if operator is Operator.GTE:
        return isinstance(value, int | float) and not isinstance(value, bool) and value >= expectation.value
    if operator is Operator.LTE:
        return isinstance(value, int | float) and not isinstance(value, bool) and value <= expectation.value
    raise ValueError(f"operator {operator.value} is not supported by valued detectors")


def scope_matches(scope: DecisionScope, subscription_id: str | None, resource_group: str | None) -> bool:
    """A decision scope against an observation that carries a subscription and maybe a resource group. Tag
    selectors cannot be evaluated on an observation (Advisor and policy rows carry no tags) and are ignored here;
    they apply to resource rows through `selector_matches` and the drift engine."""
    if scope.subscriptionIds and (subscription_id or "") not in {s.lower() for s in scope.subscriptionIds}:
        return False
    return not scope.resourceGroupNames or (resource_group or "").lower() in {
        g.lower() for g in scope.resourceGroupNames
    }


class EvidenceDetector:
    """A detector that reads normalised Azure MCP observations rather than resource rows: it receives every usable
    evidence record and answers for the claim as a whole (one finding per matching observation, or one finding
    saying nothing matched). Subclasses implement `evaluate`; `finding` builds a record the way `Detector` does."""

    detector_id: str = ""
    version: str = "1.0.0"
    question: str = ""
    tools: tuple[str, ...] = ()  # the Azure MCP tools whose results this detector reads

    def evaluate(
        self,
        claim: Claim,
        evidence: list[Evidence],
        *,
        scope: DecisionScope,
        now: datetime,
    ) -> list[DriftFinding]:
        raise NotImplementedError

    def finding(
        self,
        claim: Claim,
        verdict: Verdict,
        *,
        resource_id: str | None,
        observed: dict[str, Any],
        evidence_ids: list[str],
        now: datetime,
        unknown_reason: str | None = None,
    ) -> DriftFinding:
        return DriftFinding(
            findingId=new_id("finding"),
            claimId=claim.claimId,
            decisionId=claim.decisionId,
            resourceId=resource_id,
            verdict=verdict,
            observed=observed,
            expected={claim.expectation.property: claim.expectation.value},
            evidenceIds=list(evidence_ids),
            unknownReason=unknown_reason,
            detectorId=self.detector_id,
            detectorVersion=self.version,
            evaluatedAt=now,
        )
