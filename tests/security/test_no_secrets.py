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
# Compiled bytecode embeds the absolute path of the checkout, so a path that happens to contain a GUID (a temporary or
# CI directory) would be reported as a real identifier in the tree. Bytecode caches are build output, not source.
SKIP_SUFFIXES = {".lock", ".png", ".ico", ".pyc", ".pyo"}
SKIP_DIRS = {"__pycache__"}


def files(root: Path = ROOT):
    for entry in SCAN:
        path = root / entry
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (
                p
                for p in path.rglob("*")
                if p.is_file()
                and p.suffix not in SKIP_SUFFIXES
                and not SKIP_DIRS.intersection(p.relative_to(root).parts)
            )


def guid_offenders(root: Path = ROOT) -> list[str]:
    offenders = []
    for path in files(root):
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            for guid in GUID.findall(line):
                if not PLACEHOLDER.match(guid) and guid.lower() not in ALLOWED_GUIDS:
                    offenders.append(f"{path.relative_to(root).as_posix()}:{n}: {guid}")
    return offenders


def test_no_real_guids_outside_placeholders():
    assert guid_offenders() == []


def test_guid_scan_ignores_bytecode_caches_but_still_flags_a_real_guid_in_source(tmp_path):
    # Built at run time so this file does not itself contain a real-looking identifier.
    real = "-".join(["8a1f3c2e", "5b7d", "4e6a", "9c0b", "1d2e3f4a5b6c"])
    cache = tmp_path / "src" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "mod.cpython-314.pyc").write_bytes(f"/tmp/{real}/checkout/src/mod.py".encode())
    (cache / "note.txt").write_text(f"/tmp/{real}/checkout\n", encoding="utf-8")
    # The suffix filter must work on its own, outside any __pycache__ directory.
    (tmp_path / "src" / "mod.pyc").write_bytes(f"/tmp/{real}/checkout/src/mod.py".encode())
    (tmp_path / "src" / "legacy.pyo").write_bytes(f"/tmp/{real}/checkout/src/mod.py".encode())
    assert guid_offenders(tmp_path) == []
    (tmp_path / "src" / "mod.py").write_text(f"IDENTIFIER = '{real}'\n", encoding="utf-8")
    assert guid_offenders(tmp_path) == [f"src/mod.py:1: {real}"]


def test_no_secret_shaped_strings_and_no_client_secret_credentials():
    offenders = []
    for path in files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if SECRET_SHAPED.search(text) and "test_redaction" not in path.name and path.name != "test_no_secrets.py":
            offenders.append(str(path.relative_to(ROOT)))
        if path.suffix == ".py" and CREDENTIAL_PATHS.search(text) and path.name != "test_no_secrets.py":
            offenders.append(f"{path.relative_to(ROOT)}: client-secret credential path")
    assert offenders == []
