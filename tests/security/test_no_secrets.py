"""No secret-shaped strings, no real identifiers, no client-secret credential paths anywhere in the tree."""

from __future__ import annotations

import re
import shutil
import subprocess
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


def _git_files(root: Path) -> list[Path] | None:
    """Files git knows about under `root` (tracked, or untracked but not ignored), or None when git cannot say.

    Asking git means the scan reads exactly what would be committed: ignored build output (bytecode caches, virtual
    environments, coverage data) is never read, wherever the checkout lives."""
    git = shutil.which("git")
    if git is None or not (root / ".git").exists():
        return None
    done = subprocess.run(  # noqa: S603 # nosec B603 - fixed argument list, no shell, no user input
        [git, "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=False,
    )
    if done.returncode != 0:
        return None
    names = [n for n in done.stdout.decode("utf-8", errors="surrogateescape").split("\0") if n]
    return [root / n for n in names]


def _in_scope(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    top = relative.parts[0]
    return (
        (top in SCAN)
        and path.is_file()
        and not path.is_symlink()
        and path.suffix not in SKIP_SUFFIXES
        and not SKIP_DIRS.intersection(relative.parts)
    )


def files(root: Path = ROOT):
    """The text files to scan: git's list when the root is a git checkout, otherwise a walk of the same folders.

    Both routes apply the same scope (`SCAN`) and the same exclusions (bytecode, caches, binary suffixes), so a
    checkout whose absolute path contains a GUID cannot produce a hit that is not in a source file."""
    listed = _git_files(root)
    if listed is not None:
        yield from (p for p in listed if _in_scope(p, root))
        return
    for entry in SCAN:
        path = root / entry
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (p for p in path.rglob("*") if _in_scope(p, root))


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


def _git(root: Path, *args: str) -> None:
    git = shutil.which("git")
    assert git is not None, "git is required for this test"
    subprocess.run([git, "-C", str(root), *args], check=True, capture_output=True)  # noqa: S603 # nosec B603


def test_git_route_skips_ignored_output_and_still_flags_a_real_guid_in_a_planted_file(tmp_path):
    # Negative control for the git-based file list: a throwaway repository, an ignored cache that embeds a GUID path,
    # then a real-looking GUID planted in a tracked-style source file. The GUID is built at run time.
    real = "-".join(["8a1f3c2e", "5b7d", "4e6a", "9c0b", "1d2e3f4a5b6c"])
    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "build").mkdir()
    (tmp_path / "src" / "ok.py").write_text("SUBSCRIPTION = '00000000-0000-0000-0000-000000000001'\n", encoding="utf-8")
    (tmp_path / "build" / "out.txt").write_text(f"/tmp/{real}/checkout\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    assert _git_files(tmp_path) is not None
    assert guid_offenders(tmp_path) == []
    (tmp_path / "docs" / "planted.md").write_text(f"tenant {real}\n", encoding="utf-8")
    assert guid_offenders(tmp_path) == [f"docs/planted.md:1: {real}"]
    # Outside the scanned folders nothing is read, as before.
    (tmp_path / "elsewhere.txt").write_text(f"{real}\n", encoding="utf-8")
    assert guid_offenders(tmp_path) == [f"docs/planted.md:1: {real}"]


def test_scan_passes_from_a_checkout_path_that_contains_a_guid(tmp_path):
    # The case in ticket #13: the checkout folder itself is named with a GUID, and bytecode embeds that path.
    real = "-".join(["8a1f3c2e", "5b7d", "4e6a", "9c0b", "1d2e3f4a5b6c"])
    root = tmp_path / real / "checkout"
    (root / "src" / "__pycache__").mkdir(parents=True)
    (root / "src" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "src" / "__pycache__" / "mod.cpython-314.pyc").write_bytes(str(root / "src" / "mod.py").encode())
    for use_git in (False, True):
        if use_git:
            _git(root, "init", "-q")
        assert guid_offenders(root) == [], f"git={use_git}"
    (root / "src" / "leak.py").write_text(f"ID = '{real}'\n", encoding="utf-8")
    assert guid_offenders(root) == [f"src/leak.py:1: {real}"]
