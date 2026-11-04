#!/usr/bin/env bash
# requirements.lock.txt is the hash-pinned export of uv.lock the Dockerfile installs from. CI fails when it drifts.
# The export itself is scripts/export-lockfiles.sh, the same one `make lock` and the Dependabot workflow run.
set -euo pipefail
cd "$(dirname "$0")/.."
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
bash scripts/export-lockfiles.sh "$tmp"
if ! diff -u requirements.lock.txt "$tmp/requirements.lock.txt"; then
  echo "requirements.lock.txt drifted from uv.lock; run: make lock" >&2
  exit 1
fi
echo "lockfile export matches uv.lock"
