#!/usr/bin/env bash
# requirements.lock.txt is the hash-pinned export of uv.lock the Dockerfile installs from. CI fails when it drifts.
set -euo pipefail
cd "$(dirname "$0")/.."
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
uv export --frozen --format requirements-txt --no-dev --no-emit-project --no-emit-workspace --no-header -o "$tmp" >/dev/null
if ! diff -u requirements.lock.txt "$tmp"; then
  echo "requirements.lock.txt drifted from uv.lock; run: make lock" >&2
  exit 1
fi
echo "lockfile export matches uv.lock"
