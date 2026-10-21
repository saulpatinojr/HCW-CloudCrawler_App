"""Verify a cloud-crawler-core wheel before it is attached to a release (publish-core.yml) or adopted downstream.

The engine moves to the AddOn unchanged (ADR 0002), and the AddOn's boundary forbids any cloud SDK and any Azure
endpoint in its image. So the wheel must carry the detector registry and the normalisers, import nothing but the
standard library and pydantic, and name no Azure endpoint. Exit 1 with the reason otherwise.
"""

from __future__ import annotations

import glob
import re
import sys
import zipfile

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
        requires = [line for line in archive.read(metadata).decode().splitlines() if line.startswith("Requires-Dist:")]
        if any("pydantic" not in line for line in requires):
            print(f"the wheel requires more than pydantic: {requires}")
            return 1
    print(f"wheel verified: {wheel}, {len(names)} files, requires {requires}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "dist/cloud_crawler_core-*.whl"))
