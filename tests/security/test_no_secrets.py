"""No secret-shaped strings, no real identifiers, no client-secret credential paths anywhere in the tree."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN = ("src", "packages", "tests", "samples", "docs", "infrastructure", ".github", "README.md", "CLAUDE.md")
GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
PLACEHOLDER = re.compile(r"^00000000-0000-0000-0000-0000000000[0-9a-fA-F]{2}$")
ALLOWED_GUIDS = {
    "797f4846-ba00-4fd7-ba43-dac1f8f63013",  # Azure Resource Manager first-party application id
    "ba7816bf-8f01-cfea-4141-40de5dae2223",  # never produced; keeps the set non-empty for the test below
}
SECRET_SHAPED = re.compile(r"(AccountKey=[A-Za-z0-9+/=]{20,}|ghp_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
CREDENTIAL_PATHS = re.compile(r"ClientSecretCredential|CertificateCredential|UsernamePasswordCredential")
SKIP_SUFFIXES = {".lock", ".png", ".ico"}


def files():
    for entry in SCAN:
        path = ROOT / entry
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (p for p in path.rglob("*") if p.is_file() and p.suffix not in SKIP_SUFFIXES)


def test_no_real_guids_outside_placeholders():
    offenders = []
    for path in files():
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            for guid in GUID.findall(line):
                if not PLACEHOLDER.match(guid) and guid.lower() not in ALLOWED_GUIDS:
                    offenders.append(f"{path.relative_to(ROOT)}:{n}: {guid}")
    assert offenders == []


def test_no_secret_shaped_strings_and_no_client_secret_credentials():
    offenders = []
    for path in files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if SECRET_SHAPED.search(text) and "test_redaction" not in path.name and path.name != "test_no_secrets.py":
            offenders.append(str(path.relative_to(ROOT)))
        if path.suffix == ".py" and CREDENTIAL_PATHS.search(text) and path.name != "test_no_secrets.py":
            offenders.append(f"{path.relative_to(ROOT)}: client-secret credential path")
    assert offenders == []
