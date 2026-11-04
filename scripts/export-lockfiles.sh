#!/usr/bin/env bash
# Writes requirements.lock.txt, the hash-pinned export of uv.lock the Dockerfile installs from, into the directory
# given (default: the repository root). The one place the export flags live: `make lock`, scripts/check-lockfiles.sh
# and .github/workflows/dependabot-lockfiles.yml all call it. --frozen reads uv.lock as it is: nothing is resolved,
# downloaded or built, so no dependency code runs.
set -euo pipefail
cd "$(dirname "$0")/.."
out="${1:-.}"
uv export --frozen --format requirements-txt --no-dev --no-emit-project --no-emit-workspace --no-header -q \
  -o "$out/requirements.lock.txt"
