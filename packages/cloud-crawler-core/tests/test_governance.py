from __future__ import annotations

import pytest
from cloud_crawler_core.detectors import DETECTORS, get_detector
from cloud_crawler_core.detectors.base import ANY_TYPE, compare
from cloud_crawler_core.detectors.governance import REGION_ALLOWED, SKU_ALLOWED, TAG_REQUIRED
from cloud_crawler_core.models import Expectation, NormalizedResource, Operator, Verdict
from core_fixtures import NOW, make_decision


def resource(rtype: str = "microsoft.keyvault/vaults", **kwargs) -> NormalizedResource:
    base = {
        "id": f"/subscriptions/00000000-0000-0000-0000-000000000001/x/{rtype}",
        "type": rtype,
        "name": "hcw-sample-x",
        "location": "centralus",
        "tags": {"Env": "prod", "owner": "platform-team"},
        "sku": {"name": "Standard_ZRS", "tier": "Standard"},
    }
    base.update(kwargs)
    return NormalizedResource(**base)


def test_registry_holds_every_wave_one_detector():
    assert {
        "zone-redundancy",
        "public-access-disabled",
        "private-endpoint-present",
        "managed-identity",
        "tag-required",
        "sku-allowed",
        "region-allowed",
    } <= set(DETECTORS)
    assert all(get_detector(d).detector_id == d for d in DETECTORS)
    assert all(d.valued for d in (TAG_REQUIRED, SKU_ALLOWED, REGION_ALLOWED))
    assert TAG_REQUIRED.resource_types == (ANY_TYPE,)


def test_tag_reader_matches_names_case_insensitively():
    read = TAG_REQUIRED.readers[ANY_TYPE]
    assert read(resource(), {"tag": "env"}).value == "prod"
    assert read(resource(), {"tag": "OWNER"}).value == "platform-team"
    missing = read(resource(), {"tag": "costCenter"})
    assert missing.answer is True and missing.value is None
    assert read(resource(), {}).answer is None


def test_sku_and_region_readers():
    assert SKU_ALLOWED.readers[ANY_TYPE](resource(), {}).value == "Standard_ZRS"
    assert SKU_ALLOWED.readers[ANY_TYPE](resource(), {"field": "tier"}).value == "Standard"
    assert SKU_ALLOWED.readers[ANY_TYPE](resource(), {"field": "size"}).answer is None
    assert SKU_ALLOWED.readers[ANY_TYPE](resource(sku={}), {}).answer is None
    assert REGION_ALLOWED.readers[ANY_TYPE](resource(), {}).value == "centralus"
    assert REGION_ALLOWED.readers[ANY_TYPE](resource(location=None), {}).answer is None


@pytest.mark.parametrize(
    ("operator", "expected", "value", "holds"),
    [
        (Operator.EXISTS, None, "x", True),
        (Operator.EXISTS, None, None, False),
        (Operator.ABSENT, None, None, True),
        (Operator.ABSENT, None, "x", False),
        (Operator.EQ, "East US 2", "eastus2", True),
        (Operator.EQ, "eastus2", None, False),
        (Operator.NEQ, "eastus2", "centralus", True),
        (Operator.NEQ, "eastus2", None, True),
        (Operator.IN, ["centralus", "East US 2"], "eastus2", True),
        (Operator.IN, ["centralus"], "eastus2", False),
        (Operator.IN, ["centralus"], None, False),
        (Operator.GTE, 2, 3, True),
        (Operator.GTE, 2, True, False),
        (Operator.LTE, 2, 3, False),
        (Operator.LTE, 2, "3", False),
    ],
)
def test_compare(operator, expected, value, holds):
    assert compare(Expectation(property="p", operator=operator, value=expected), value) is holds


def test_compare_rejects_unsupported_operator():
    with pytest.raises(ValueError, match="not supported"):
        compare(Expectation(property="p", operator=Operator.SUBSET, value=[]), [])


def test_valued_evaluation_end_to_end():
    decision = make_decision(
        detector_id="region-allowed",
        expectation=Expectation(property="location", operator=Operator.IN, value=["centralus"]),
    )
    claim = decision.claims[0]
    rows = [
        resource("microsoft.sql/servers/databases", id="/a"),
        resource("microsoft.sql/servers/databases", id="/b", location="eastus2"),
        resource("microsoft.sql/servers/databases", id="/c", location=None),
        resource("microsoft.keyvault/vaults", id="/d"),  # outside the claim's selector
    ]
    findings = REGION_ALLOWED.evaluate(claim, rows, evidence_ids=["ev_1"], now=NOW)
    verdicts = {f.resourceId: f.verdict for f in findings}
    assert verdicts == {
        "/a": Verdict.SUPPORTED,
        "/b": Verdict.CONTRADICTED,
        "/c": Verdict.UNKNOWN,
        "/d": Verdict.NOT_APPLICABLE,
    }
    contradicted = next(f for f in findings if f.resourceId == "/b")
    assert contradicted.observed == {"location": "eastus2", "reading": "eastus2"}
    assert contradicted.expected == {"location": ["centralus"]}


def test_tag_required_exists_contradicts_a_missing_tag():
    decision = make_decision(
        detector_id="tag-required", expectation=Expectation(property="tag", operator=Operator.EXISTS)
    )
    claim = decision.claims[0].model_copy(update={"parameters": {"tag": "costCenter"}})
    [finding] = TAG_REQUIRED.evaluate(claim, [resource("microsoft.sql/servers/databases")], evidence_ids=[], now=NOW)
    assert finding.verdict is Verdict.CONTRADICTED and finding.observed == {"tag": None, "reading": None}


@pytest.mark.parametrize(
    ("expectation", "message"),
    [
        (Expectation(property="tag", operator=Operator.SUBSET, value=[]), "takes expectation"),
        (Expectation(property="tag", operator=Operator.IN, value="x"), "takes a list"),
        (Expectation(property="tag", operator=Operator.GTE, value="x"), "takes a number"),
    ],
)
def test_valued_expectation_authoring_errors(expectation, message):
    decision = make_decision(detector_id="tag-required", expectation=expectation)
    with pytest.raises(ValueError, match=message):
        TAG_REQUIRED.evaluate(
            decision.claims[0], [resource("microsoft.sql/servers/databases")], evidence_ids=[], now=NOW
        )
