from __future__ import annotations

import pytest
from cloud_crawler_core.detectors import DETECTORS, get_detector
from cloud_crawler_core.detectors.zone_redundancy import ZONE_REDUNDANCY
from cloud_crawler_core.models import Expectation, NormalizedResource, Operator, Selector, Verdict
from core_fixtures import NOW, make_decision


def resource(rtype: str, **kwargs) -> NormalizedResource:
    base = {
        "id": f"/subscriptions/00000000-0000-0000-0000-000000000001/x/{rtype}",
        "type": rtype,
        "name": "hcw-sample-x",
        "tags": {"env": "prod"},
    }
    base.update(kwargs)
    return NormalizedResource(**base)


def test_registry_knows_zone_redundancy():
    assert get_detector("zone-redundancy") is ZONE_REDUNDANCY
    assert "zone-redundancy" in DETECTORS
    with pytest.raises(KeyError):
        get_detector("nope")
    assert ZONE_REDUNDANCY.resource_types == tuple(sorted(ZONE_REDUNDANCY.readers))


@pytest.mark.parametrize(
    ("rtype", "kwargs", "answer"),
    [
        ("microsoft.sql/servers/databases", {"properties": {"zoneRedundant": True}}, True),
        ("microsoft.sql/servers/databases", {"properties": {"zoneRedundant": "false"}}, False),
        ("microsoft.sql/servers/databases", {"properties": {}}, None),
        ("microsoft.storage/storageaccounts", {"sku": {"name": "Standard_GZRS"}}, True),
        ("microsoft.storage/storageaccounts", {"sku": {"name": "Premium_LRS"}}, False),
        ("microsoft.storage/storageaccounts", {"sku": {}}, None),
        ("microsoft.web/serverfarms", {"properties": {"zoneRedundant": True}}, True),
        ("microsoft.web/serverfarms", {"properties": {"zoneRedundant": None}}, None),
        (
            "microsoft.dbforpostgresql/flexibleservers",
            {"properties": {"highAvailability": {"mode": "ZoneRedundant"}}},
            True,
        ),
        (
            "microsoft.dbforpostgresql/flexibleservers",
            {"properties": {"highAvailability": {"mode": "SameZone"}}},
            False,
        ),
        ("microsoft.dbforpostgresql/flexibleservers", {"properties": {"highAvailability": {}}}, None),
        ("microsoft.documentdb/databaseaccounts", {"properties": {"locations": [{"isZoneRedundant": True}]}}, True),
        (
            "microsoft.documentdb/databaseaccounts",
            {"properties": {"locations": [{"isZoneRedundant": True}, {"isZoneRedundant": False}]}},
            False,
        ),
        ("microsoft.documentdb/databaseaccounts", {"properties": {"locations": [{"x": 1}]}}, None),
        ("microsoft.documentdb/databaseaccounts", {"properties": {}}, None),
        (
            "microsoft.containerservice/managedclusters",
            {"properties": {"agentPoolProfiles": [{"availabilityZones": ["1", "2"]}]}},
            True,
        ),
        (
            "microsoft.containerservice/managedclusters",
            {"properties": {"agentPoolProfiles": [{"availabilityZones": ["1"]}, {}]}},
            False,
        ),
        ("microsoft.containerservice/managedclusters", {"properties": {}}, None),
        ("microsoft.compute/virtualmachines", {"zones": ["1"]}, None),  # a row cannot prove redundancy
        ("microsoft.compute/virtualmachines", {}, None),
        ("microsoft.compute/virtualmachinescalesets", {"zones": ["1", "2"]}, True),
        ("microsoft.compute/virtualmachinescalesets", {"zones": ["1"]}, False),
        ("microsoft.network/publicipaddresses", {"zones": ["1", "2", "3"]}, True),
        ("microsoft.network/publicipaddresses", {"zones": ["1"]}, False),
    ],
)
def test_readers(rtype, kwargs, answer):
    reader = ZONE_REDUNDANCY.readers[rtype]
    assert reader(resource(rtype, **kwargs), {}).answer is answer


def test_virtual_machine_rows_say_why_they_are_unknown():
    r = resource("microsoft.compute/virtualmachines", zones=["1"])
    assert "instance set" in (ZONE_REDUNDANCY.readers[r.type](r, {}).reason or "")
    assert "not implemented" in (ZONE_REDUNDANCY.readers[r.type](r, {"instanceSet": "app"}).reason or "")


def test_aks_minimum_zones_parameter():
    r = resource(
        "microsoft.containerservice/managedclusters",
        properties={"agentPoolProfiles": [{"availabilityZones": ["1", "2"]}]},
    )
    assert ZONE_REDUNDANCY.readers[r.type](r, {"minimumZones": 3}).answer is False


def test_evaluate_maps_readings_to_verdicts_and_selector():
    decision = make_decision(
        selector=Selector(resourceTypes=["microsoft.sql/servers/databases"], tagSelectors={"env": "prod"})
    )
    claim = decision.claims[0]
    rows = [
        resource("microsoft.sql/servers/databases", id="/a", properties={"zoneRedundant": True}),
        resource("microsoft.sql/servers/databases", id="/b", properties={"zoneRedundant": False}),
        resource("microsoft.sql/servers/databases", id="/c", properties={}),
        resource("microsoft.sql/servers/databases", id="/d", tags={"env": "dev"}, properties={"zoneRedundant": False}),
        resource("microsoft.keyvault/vaults", id="/e"),
    ]
    findings = ZONE_REDUNDANCY.evaluate(claim, rows, evidence_ids=["ev_1"], now=NOW)
    verdicts = {f.resourceId: f.verdict for f in findings}
    assert verdicts == {
        "/a": Verdict.SUPPORTED,
        "/b": Verdict.CONTRADICTED,
        "/c": Verdict.UNKNOWN,
        "/d": Verdict.NOT_APPLICABLE,
        "/e": Verdict.NOT_APPLICABLE,
    }
    unknown = next(f for f in findings if f.resourceId == "/c")
    assert unknown.unknownReason == "properties.zoneRedundant is absent"
    assert all(f.evidenceIds == ["ev_1"] and f.detectorVersion == "1.0.0" for f in findings)


def test_negated_expectation_flips_verdict():
    decision = make_decision(expectation=Expectation(property="zoneRedundant", operator=Operator.NEQ, value=True))
    [finding] = ZONE_REDUNDANCY.evaluate(
        decision.claims[0],
        [resource("microsoft.sql/servers/databases", properties={"zoneRedundant": False})],
        evidence_ids=[],
        now=NOW,
    )
    assert finding.verdict is Verdict.SUPPORTED


def test_non_boolean_expectation_is_an_authoring_error():
    decision = make_decision(expectation=Expectation(property="zoneRedundant", operator=Operator.IN, value=[True]))
    with pytest.raises(ValueError, match="eq/neq true|false"):
        ZONE_REDUNDANCY.evaluate(
            decision.claims[0], [resource("microsoft.sql/servers/databases")], evidence_ids=[], now=NOW
        )


def test_selector_name_globs_and_subscriptions():
    decision = make_decision(
        selector=Selector(nameGlobs=["hcw-sample-*"], subscriptionIds=["00000000-0000-0000-0000-000000000002"])
    )
    [finding] = ZONE_REDUNDANCY.evaluate(
        decision.claims[0],
        [
            resource(
                "microsoft.sql/servers/databases",
                subscriptionId="00000000-0000-0000-0000-000000000001",
                properties={"zoneRedundant": True},
            )
        ],
        evidence_ids=[],
        now=NOW,
    )
    assert finding.verdict is Verdict.NOT_APPLICABLE
