#!/usr/bin/env bash
# The base image in infrastructure/docker/versions.env (PYTHON_IMAGE@PYTHON_IMAGE_DIGEST, and PYTHON_VERSION inside the
# tag) equals every FROM in the Dockerfile that is not an earlier stage. Ported from the Cloud Assessor App's
# scripts/check-versions.sh. Run by ci.yml (lint job) and `make lint`; exits non-zero on drift.
# Usage: bash scripts/check-versions.sh [Dockerfile] [versions.env]
set -euo pipefail
cd "$(dirname "$0")/.."
DOCKERFILE=${1:-infrastructure/docker/Dockerfile}
VERSIONS=${2:-infrastructure/docker/versions.env}
image="$(sed -n 's/^PYTHON_IMAGE=//p' "$VERSIONS")"
digest="$(sed -n 's/^PYTHON_IMAGE_DIGEST=//p' "$VERSIONS")"
version="$(sed -n 's/^PYTHON_VERSION=//p' "$VERSIONS")"
want="${image}@${digest}"
if ! [[ "$want" =~ ^python:[^@[:space:]]+@sha256:[0-9a-f]{64}$ ]]; then
  echo "::error file=${VERSIONS}::PYTHON_IMAGE@PYTHON_IMAGE_DIGEST is not python:<tag>@sha256:<64 lowercase hex>"; exit 1
fi
case "$image" in
  "python:${version}-"*) ;;
  *) echo "::error file=${VERSIONS}::PYTHON_IMAGE ${image} does not carry PYTHON_VERSION ${version:-<empty>}"; exit 1 ;;
esac
stages=" "; bad=0; seen=0
# Docker reads instruction keywords in any case and allows leading whitespace; flags such as --platform come first.
while read -r -a words; do
  set -- "${words[@]:1}"
  while [ $# -gt 0 ] && [[ "$1" == --* ]]; do shift; done
  from=${1:-}; as=${2:-}; name=${3:-}
  seen=$((seen + 1))
  if [[ "$stages" == *" ${from} "* ]]; then echo "ok FROM ${from} (earlier stage)"
  elif [ "$from" = "$want" ]; then echo "ok FROM ${from}"
  else echo "::error file=${DOCKERFILE}::FROM ${from} is neither an earlier stage nor ${want}"; bad=1; fi
  if [ "${as,,}" = as ] && [ -n "$name" ]; then stages="${stages}${name} "; fi
done < <(grep -iE '^[[:space:]]*FROM[[:space:]]' "$DOCKERFILE")
if [ "$seen" -eq 0 ]; then echo "::error file=${DOCKERFILE}::no FROM line"; exit 1; fi
exit $bad
