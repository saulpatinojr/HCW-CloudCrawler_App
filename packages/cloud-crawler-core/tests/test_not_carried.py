"""`notCarried`: a row from evidence that cannot say what identity, tags or zones hold makes the detectors that read
them answer unknown, where an empty field in a Resource Graph export is a definite "none" (ticket #54)."""

from __future__ import annotations

from pathlib import Path

import pytest
from cloud_crawler_core import detectors
from cloud_crawler_core.detectors.base import not_carried
from cloud_crawler_core.detectors.governance import TAG_REQUIRED
from cloud_crawler_core.detectors.identity import MANAGED_IDENTITY
from cloud_crawler_core.detectors.zone_redundancy import ZONE_REDUNDANCY
from cloud_crawler_core.models import Claim, Expectation, NormalizedResource, Operator, Verdict
from core_fixtures import NOW


def row(rtype: str, **kwargs) -> NormalizedResource:
    base = {"id": f"/subscriptions/00000000-0000-0000-0000-000000000001/x/{rtype}", "type": rtype, "name": "n"}
    base.update(kwargs)
    return NormalizedResource(**base)


def test_the_helper_answers_only_for_the_fields_a_row_lists():
    listed = row("microsoft.web/sites", notCarried=["tags"])
    assert not_carried(listed, "tags").answer is None and "tags" in not_carried(listed, "tags").reason
    assert not_carried(listed, "identity") is None and not_carried(row("microsoft.web/sites"), "tags") is None


def test_a_resource_graph_row_has_nothing_unsaid():
    assert row("microsoft.web/sites").notCarried == []


@pytest.mark.parametrize(
    ("rtype", "reader", "field", "empty_means"),
    [
        ("microsoft.web/sites", MANAGED_IDENTITY.readers["microsoft.web/sites"], "identity", False),
        (
            "microsoft.network/publicipaddresses",
            ZONE_REDUNDANCY.readers["microsoft.network/publicipaddresses"],
            "zones",
            False,
        ),
        (
            "microsoft.compute/virtualmachinescalesets",
            ZONE_REDUNDANCY.readers["microsoft.compute/virtualmachinescalesets"],
            "zones",
            False,
        ),
        ("microsoft.web/sites", TAG_REQUIRED.readers["*"], "tags", True),
    ],
)
def test_readers_answer_unknown_for_a_field_that_is_not_carried_and_definitely_for_one_that_is_empty(
    rtype, reader, field, empty_means
):
    parameters = {"tag": "owner"}
    empty = reader(row(rtype), parameters)  # an export that omits the field: it is none
    assert empty.answer is empty_means and empty.reason is None
    unsaid = reader(row(rtype, notCarried=[field]), parameters)
    assert unsaid.answer is None and field in (unsaid.reason or "")


def test_a_detector_run_gives_an_unknown_finding_with_the_reason():
    from cloud_crawler_core.models import Selector

    claim = Claim(
        claimId="claim_1",
        decisionId="decision_1",
        statement="has an owner",
        detectorId="tag-required",
        parameters={"tag": "owner"},
        selector=Selector(),
        expectation=Expectation(property="tag", operator=Operator.EXISTS),
    )
    [definite] = TAG_REQUIRED.evaluate(claim, [row("microsoft.web/sites")], evidence_ids=["e"], now=NOW)
    assert definite.verdict is Verdict.CONTRADICTED  # an export without the tag: it is missing
    [unsaid] = TAG_REQUIRED.evaluate(
        claim, [row("microsoft.web/sites", notCarried=["tags"])], evidence_ids=["e"], now=NOW
    )
    assert unsaid.verdict is Verdict.UNKNOWN and "tags" in unsaid.unknownReason


def test_every_detector_module_that_reads_identity_tags_or_zones_honours_notcarried():
    # The readers that treat an absent identity, tags or zones as "none" must ask `not_carried` first. This fails when
    # a new reader of one of these fields is added to a detector module that never mentions it.
    package = Path(detectors.__file__).parent
    readers = {
        "identity": "resource.identity",
        "tags": "resource.tags",
        "zones": "resource.zones",
    }
    for source in sorted(package.glob("*.py")):
        if source.name in {"base.py", "__init__.py"}:
            continue
        text = source.read_text(encoding="utf-8")
        reads = [
            field for field, access in readers.items() if access in text or (field == "tags" and "tag_of(" in text)
        ]
        for field in reads:
            assert f'not_carried(resource, "{field}")' in text, f"{source.name} reads {field} without not_carried"
