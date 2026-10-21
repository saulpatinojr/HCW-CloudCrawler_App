from __future__ import annotations

import pytest
from cloud_crawler_core.detectors.identity import MANAGED_IDENTITY
from cloud_crawler_core.models import NormalizedResource


def resource(**kwargs) -> NormalizedResource:
    base = {
        "id": "/subscriptions/00000000-0000-0000-0000-000000000001/x/site",
        "type": "microsoft.web/sites",
        "name": "hcw-sample-app",
    }
    base.update(kwargs)
    return NormalizedResource(**base)


@pytest.mark.parametrize(
    ("identity", "parameters", "answer", "value"),
    [
        ({"type": "SystemAssigned"}, {}, True, "SystemAssigned"),
        ({"type": "UserAssigned"}, {}, True, "UserAssigned"),
        ({"type": "SystemAssigned, UserAssigned"}, {}, True, "SystemAssigned, UserAssigned"),
        (
            {"type": "SystemAssigned,UserAssigned"},
            {"identityType": "UserAssigned"},
            True,
            "SystemAssigned,UserAssigned",
        ),
        ({"type": "UserAssigned"}, {"identityType": "SystemAssigned"}, False, "UserAssigned"),
        ({"type": "userassigned"}, {"identityType": "user assigned"}, True, "userassigned"),
        ({"type": "None"}, {}, False, "None"),
        ({}, {}, False, "None"),  # a type that supports identities and carries none: definite
        ({"type": 3}, {}, None, 3),
        ({"type": "SystemAssigned"}, {"identityType": "Managed"}, None, "SystemAssigned"),
    ],
)
def test_identity_reader(identity, parameters, answer, value):
    reading = MANAGED_IDENTITY.readers["microsoft.web/sites"](resource(identity=identity), parameters)
    assert reading.answer is answer and reading.value == value


def test_identity_detector_is_boolean_and_lists_types():
    assert MANAGED_IDENTITY.valued is False
    assert "microsoft.compute/virtualmachines" in MANAGED_IDENTITY.resource_types
    assert MANAGED_IDENTITY.reader_for("microsoft.network/virtualnetworks") is None
