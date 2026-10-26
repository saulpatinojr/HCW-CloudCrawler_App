"""Static checks on the README's real-tenant runbook ("Checking sign-in against a real tenant").

The Cloud Assessor real-tenant run failed because its app role and its delegated scope shared one value, which Entra
refuses. These tests keep that mistake out of this runbook, and keep the runbook's values, settings and expected
answers in step with the code. They read the README only; nothing here talks to Entra.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cloud_crawler_appliance.config import DEFAULT_HUMAN_SCOPE, Settings

README = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")
START = README.index("### Checking sign-in against a real tenant")
END = README.index("\n## ", START)
RUNBOOK = README[START:END]
BLOCKS = re.findall(r"```powershell\n(.*?)```", RUNBOOK, re.DOTALL)


def _value(name: str) -> str:
    found = re.search(rf"\${name} = '([^']+)'", RUNBOOK)
    assert found, f"the runbook does not set ${name}"
    return found.group(1)


def test_the_role_and_the_scope_have_different_values():
    role, scope = _value("roleValue"), _value("scopeValue")
    assert role != scope
    assert role.lower() != scope.lower()  # Entra compares case-insensitively when it checks for duplicates


def test_the_scope_is_the_default_human_scope_and_the_role_is_a_valid_setting():
    role, scope = _value("roleValue"), _value("scopeValue")
    assert scope == DEFAULT_HUMAN_SCOPE  # the appliance needs no CC_ENTRA_HUMAN_SCOPE for this app
    env = {
        "CC_AUTH_MODE": "entra",
        "CC_ENTRA_TENANT_ID": "00000000-0000-0000-0000-000000000002",
        "CC_ENTRA_AUDIENCE": "api://00000000-0000-0000-0000-000000000003",
        "CC_AUTH_REQUIRED_ROLES": role,
    }
    assert Settings.from_env(env).auth_required_roles == (role,)


def test_every_role_and_scope_in_the_readme_is_unique_across_the_two_kinds():
    """The portal instructions and the runbook name the same two values; no role value equals a scope value."""
    roles = set(re.findall(r"CloudCrawler\.[A-Za-z]+", README)) - {"CloudCrawler.NotAssigned"}
    scopes = {_value("scopeValue"), DEFAULT_HUMAN_SCOPE}
    assert roles == {_value("roleValue")} and not roles & scopes


def test_the_runbook_uses_the_variables_not_a_second_copy_of_the_values():
    body = "\n".join(BLOCKS)
    assert "value = $roleValue" in body and "value = $scopeValue" in body
    assert "access_as_user" in body  # the scope name in the token request (step 5) is spelled out on purpose


def test_the_runbook_creates_and_removes_the_app_and_makes_every_call_it_promises():
    body = "\n".join(BLOCKS)
    for command in ("az ad app create", "az ad sp create", "appRoleAssignedTo", "az ad app delete"):
        assert command in body, command
    for number in range(1, 8):
        assert f'"{number} ' in body, f"call {number} is missing"
    # the expected answers match what the server gives
    for expected in ("(expect True entra)", "(expect 401)", "(expect 404)", "(expect 200)", "(expect 403)"):
        assert expected in body
    assert "not_found: no such decision" in RUNBOOK and "CC_ALLOW_UNAUTHENTICATED_NON_LOOPBACK" in RUNBOOK


@pytest.mark.parametrize(
    "forbidden",
    [
        "--password",
        "client_secret",
        "credential reset",
        "az ad app credential",
        "az ad sp create-for-rbac",
        "ConvertTo-SecureString",
        "Write-Host $good",
        "Write-Output $good",
        "echo $good",
        '$good"',  # the token is only ever placed in a header, never printed on its own
    ],
)
def test_the_runbook_creates_no_secret_and_never_prints_a_token(forbidden):
    body = "\n".join(BLOCKS)
    assert forbidden not in body.replace('"Authorization: Bearer $good"', "").replace(
        '"Authorization: Bearer $wrong"', ""
    )


def test_the_runbook_has_no_placeholders_and_no_real_identifiers():
    body = "\n".join(BLOCKS)
    assert not re.search(r"<[a-z][a-z -]*>", body)  # nothing for the owner to substitute
    guids = set(re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", body))
    assert guids == {"04b07795-8ddb-461a-bbee-02f9e1bf7b46"}  # only the Azure CLI's public application id


def test_each_step_fits_on_one_screen():
    steps = re.split(r"\n#### Step \d+\. ", RUNBOOK)[1:]
    assert len(steps) == 8
    for step in steps:
        assert len(step.splitlines()) <= 40, step.splitlines()[0]
