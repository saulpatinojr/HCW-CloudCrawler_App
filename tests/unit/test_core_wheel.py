"""The cloud-crawler-core wheel and sdist, built as publish-core.yml builds them, carry the MIT licence text.

The release attaches both archives and the AddOn installs the wheel, so the licence has to travel inside them (PEP 639:
``.dist-info/licenses/LICENSE`` named by ``License-File`` in the wheel, ``LICENSE`` at the top of the sdist). Up to
0.1.1 they declared ``License-Expression: MIT`` and carried no LICENSE. ``scripts/verify-core-wheel.py`` is the gate
the release runs on the wheel; this file runs it on every pull request too, and proves it refuses a wheel without the
licence.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "scripts" / "verify-core-wheel.py"


@pytest.fixture(scope="module")
def dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build as publish-core.yml does: the sdist first, then the wheel from that sdist.

    Only the tests that need a build skip without uv; the licence-copy drift test needs no uv and always runs."""
    if shutil.which("uv") is None:
        pytest.skip("uv not on PATH")
    out = tmp_path_factory.mktemp("dist")
    proc = subprocess.run(
        ["uv", "build", "--no-create-gitignore", "--package", "cloud-crawler-core", "--out-dir", str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return out


def _one(dist: Path, pattern: str) -> Path:
    found = list(dist.glob(pattern))
    assert len(found) == 1, found
    return found[0]


def _verify(wheel: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(VERIFY), str(wheel)], capture_output=True, text=True, timeout=60, check=False
    )


def test_package_licence_is_a_copy_of_the_root_licence() -> None:
    """license-files cannot point outside the package folder, so the package keeps a copy of the root LICENSE."""
    assert (ROOT / "packages/cloud-crawler-core/LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()


def test_wheel_ships_the_licence_text(dist: Path) -> None:
    wheel = _one(dist, "cloud_crawler_core-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        dist_info = next(n.split("/", 1)[0] for n in names if n.endswith(".dist-info/METADATA"))
        metadata = archive.read(f"{dist_info}/METADATA").decode("utf-8").splitlines()
        record = archive.read(f"{dist_info}/RECORD").decode("utf-8")
        shipped = archive.read(f"{dist_info}/licenses/LICENSE")
    assert "License-Expression: MIT" in metadata
    assert "License-File: LICENSE" in metadata
    assert f"{dist_info}/licenses/LICENSE," in record
    assert shipped == (ROOT / "LICENSE").read_bytes()


def test_sdist_ships_the_licence_text(dist: Path) -> None:
    sdist = _one(dist, "cloud_crawler_core-*.tar.gz")
    with tarfile.open(sdist) as archive:
        top = archive.getnames()[0].split("/", 1)[0]
        pkg_info = archive.extractfile(f"{top}/PKG-INFO").read().decode("utf-8").splitlines()
        shipped = archive.extractfile(f"{top}/LICENSE").read()
    assert "License-Expression: MIT" in pkg_info
    assert "License-File: LICENSE" in pkg_info
    assert shipped == (ROOT / "LICENSE").read_bytes()


def test_release_gate_accepts_the_built_wheel(dist: Path) -> None:
    proc = _verify(_one(dist, "cloud_crawler_core-*.whl"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "wheel verified" in proc.stdout


def test_release_gate_refuses_a_wheel_without_the_licence(dist: Path, tmp_path: Path) -> None:
    wheel = _one(dist, "cloud_crawler_core-*.whl")
    stripped = tmp_path / wheel.name
    with zipfile.ZipFile(wheel) as src, zipfile.ZipFile(stripped, "w") as dst:
        for item in src.infolist():
            if not item.filename.endswith(".dist-info/licenses/LICENSE"):
                dst.writestr(item, src.read(item))
    proc = _verify(stripped)
    assert proc.returncode == 1
    assert "does not carry the licence text" in proc.stdout


def _rewrite(wheel: Path, out: Path, replace: dict[str, bytes]) -> Path:
    """Copy the wheel, replacing the members whose names end with a key of ``replace``."""
    target = out / wheel.name
    with zipfile.ZipFile(wheel) as src, zipfile.ZipFile(target, "w") as dst:
        for item in src.infolist():
            data = src.read(item)
            for suffix, new in replace.items():
                if item.filename.endswith(suffix):
                    data = new(data) if callable(new) else new
            dst.writestr(item, data)
    return target


def test_release_gate_refuses_a_licence_that_is_only_the_mit_heading(dist: Path, tmp_path: Path) -> None:
    """Copilot on #94: a file that says "MIT License" but not the MIT terms must not pass."""
    wheel = _one(dist, "cloud_crawler_core-*.whl")
    proc = _verify(
        _rewrite(wheel, tmp_path, {".dist-info/licenses/LICENSE": b"MIT License\nThis is not the MIT text.\n"})
    )
    assert proc.returncode == 1
    assert "is not this repository's LICENSE" in proc.stdout


def test_release_gate_refuses_a_wheel_not_declared_mit(dist: Path, tmp_path: Path) -> None:
    wheel = _one(dist, "cloud_crawler_core-*.whl")
    proc = _verify(
        _rewrite(
            wheel,
            tmp_path,
            {
                ".dist-info/METADATA": lambda data: data.replace(
                    b"License-Expression: MIT", b"License-Expression: Apache-2.0"
                )
            },
        )
    )
    assert proc.returncode == 1
    assert "does not declare License-Expression: MIT" in proc.stdout
