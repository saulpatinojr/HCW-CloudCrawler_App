"""scripts/check-versions.sh: versions.env and every FROM of the Dockerfile name the same base image and digest.

Runs the script against the real files, then against mutated copies, so a drifted digest, a drifted tag, a
PYTHON_VERSION that the tag does not carry and a versions.env without a digest each fail."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check-versions.sh"
DOCKERFILE = ROOT / "infrastructure" / "docker" / "Dockerfile"
VERSIONS = ROOT / "infrastructure" / "docker" / "versions.env"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")


def run(*args: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *map(str, args)], cwd=ROOT, capture_output=True, text=True, timeout=60)


def pin() -> tuple[str, str]:
    values = dict(line.split("=", 1) for line in VERSIONS.read_text(encoding="utf-8").splitlines() if "=" in line)
    return values["PYTHON_IMAGE"], values["PYTHON_IMAGE_DIGEST"]


def test_the_real_files_agree():
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    image, digest = pin()
    froms = [line for line in DOCKERFILE.read_text(encoding="utf-8").splitlines() if line.startswith("FROM ")]
    assert result.stdout.count("ok FROM") == len(froms) >= 2
    assert f"{image}@{digest}" in result.stdout


def test_a_from_with_a_different_digest_fails(tmp_path):
    _, digest = pin()
    other = "sha256:" + "0" * 64
    assert digest != other
    text = DOCKERFILE.read_text(encoding="utf-8")
    first, rest = text.split(digest, 1)
    mutated = tmp_path / "Dockerfile"
    mutated.write_text(first + other + rest, encoding="utf-8")
    result = run(mutated, VERSIONS)
    assert result.returncode == 1
    assert "is neither an earlier stage nor" in result.stdout


def test_a_from_with_a_different_tag_fails(tmp_path):
    image, _ = pin()
    mutated = tmp_path / "Dockerfile"
    mutated.write_text(DOCKERFILE.read_text(encoding="utf-8").replace(image, "python:3.14.9-slim-trixie"), "utf-8")
    assert run(mutated, VERSIONS).returncode == 1


def test_a_from_that_names_an_earlier_stage_passes(tmp_path):
    image, digest = pin()
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(f"FROM {image}@{digest} AS build\nFROM build AS final\n", encoding="utf-8")
    result = run(dockerfile, VERSIONS)
    assert result.returncode == 0, result.stdout
    assert "(earlier stage)" in result.stdout


@pytest.mark.parametrize(
    "replace",
    [
        ("PYTHON_IMAGE_DIGEST=sha256:", "PYTHON_IMAGE_DIGEST=latest-"),  # not a digest
        ("PYTHON_VERSION=3.14.10", "PYTHON_VERSION=3.14.9"),  # the tag no longer carries the version
    ],
)
def test_a_broken_versions_env_fails(tmp_path, replace):
    text = VERSIONS.read_text(encoding="utf-8")
    assert replace[0] in text
    broken = tmp_path / "versions.env"
    broken.write_text(text.replace(replace[0], replace[1]), encoding="utf-8")
    assert run(DOCKERFILE, broken).returncode == 1


def test_a_digest_of_64_non_hex_characters_fails(tmp_path):
    _, digest = pin()
    broken = tmp_path / "versions.env"
    broken.write_text(VERSIONS.read_text(encoding="utf-8").replace(digest, "sha256:" + "g" * 64), encoding="utf-8")
    result = run(DOCKERFILE, broken)
    assert result.returncode == 1
    assert "64 lowercase hex" in result.stdout


@pytest.mark.parametrize(
    "line",
    ["from python:3.14-slim AS late", "  From python:3.14-slim", "\tFROM --platform=linux/amd64 python:3.14-slim"],
)
def test_an_unpinned_from_in_any_case_or_indent_fails(tmp_path, line):
    image, digest = pin()
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(f"FROM {image}@{digest} AS build\n{line}\n", encoding="utf-8")
    result = run(dockerfile, VERSIONS)
    assert result.returncode == 1, result.stdout
    assert "FROM python:3.14-slim is neither an earlier stage nor" in result.stdout


def test_a_platform_flag_before_the_pinned_image_passes(tmp_path):
    image, digest = pin()
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(f"FROM --platform=$BUILDPLATFORM {image}@{digest} AS build\nfrom build\n", encoding="utf-8")
    result = run(dockerfile, VERSIONS)
    assert result.returncode == 0, result.stdout
    assert result.stdout.count("ok FROM") == 2


def test_a_dockerfile_without_from_fails(tmp_path):
    empty = tmp_path / "Dockerfile"
    empty.write_text("# no stages\n", encoding="utf-8")
    assert run(empty, VERSIONS).returncode == 1


def test_ci_and_make_lint_run_it():
    assert "bash scripts/check-versions.sh" in (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "bash scripts/check-versions.sh" in (ROOT / "Makefile").read_text(encoding="utf-8")
