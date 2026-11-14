"""Verify a cloud-crawler-core wheel before it is attached to a release (publish-core.yml) or adopted downstream.

The engine moves to the AddOn unchanged (ADR 0002), and the AddOn's boundary forbids any cloud SDK and any Azure
endpoint in its image. So the wheel must carry the detector registry and the normalisers, import nothing but the
standard library and pydantic, and name no Azure endpoint. It must also carry the MIT licence text (PEP 639: under
.dist-info/licenses/, named in METADATA, with License-Expression: MIT), byte for byte this repository's LICENSE, because
the licence asks for it to travel with every copy. Exit 1 with the reason otherwise.
"""

from __future__ import annotations

import glob
import re
import sys
import zipfile
from pathlib import Path

# The licence the wheel must carry: this repository's own LICENSE (publish-core.yml runs this from the checkout).
ROOT_LICENCE = Path(__file__).resolve().parents[1] / "LICENSE"
ENDPOINTS = ("management.azure.com", "login.microsoftonline.com", "graph.microsoft.com")
CLOUD_SDKS = r"^\s*(import|from)\s+(azure|msal|boto3|google\.cloud|httpx|requests|aiohttp|urllib3)\b"
REQUIRED = (
    "cloud_crawler_core/detectors/__init__.py",
    "cloud_crawler_core/normalize/azure_mcp.py",
    "cloud_crawler_core/drift.py",
)


def main(pattern: str) -> int:
    matches = glob.glob(pattern)
    if len(matches) != 1:
        print(f"expected exactly one wheel for {pattern}, found {len(matches)}")
        return 1
    wheel = matches[0]
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        for required in REQUIRED:
            if not any(n.endswith(required) for n in names):
                print(f"{required} is missing from the wheel")
                return 1
        for name in names:
            if not name.endswith(".py"):
                continue
            text = archive.read(name).decode("utf-8")
            if re.search(CLOUD_SDKS, text, re.M):
                print(f"{name} imports a cloud SDK or an HTTP client")
                return 1
            for endpoint in ENDPOINTS:
                if endpoint in text:
                    print(f"{name} references {endpoint}")
                    return 1
        metadata = next(n for n in names if n.endswith("METADATA"))
        metadata_lines = archive.read(metadata).decode().splitlines()
        licence = metadata.removesuffix("METADATA") + "licenses/LICENSE"
        if licence not in names or "License-File: LICENSE" not in metadata_lines:
            print("the wheel does not carry the licence text (LICENSE under .dist-info/licenses/, License-File)")
            return 1
        if "License-Expression: MIT" not in metadata_lines:
            print("the wheel's METADATA does not declare License-Expression: MIT")
            return 1
        if archive.read(licence) != ROOT_LICENCE.read_bytes():
            print(f"{licence} is not this repository's LICENSE (the MIT licence text)")
            return 1
        requires = [line for line in metadata_lines if line.startswith("Requires-Dist:")]
        if any("pydantic" not in line for line in requires):
            print(f"the wheel requires more than pydantic: {requires}")
            return 1
    print(f"wheel verified: {wheel}, {len(names)} files, requires {requires}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "dist/cloud_crawler_core-*.whl"))
