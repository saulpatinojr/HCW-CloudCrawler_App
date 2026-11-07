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
# The Dockerfile without the bodies of its heredocs (`RUN <<EOF` ... `EOF`): a line inside one is text, not an
# instruction, so a `FROM` there must not be read as a stage. `<<-` strips leading tabs before the closing word,
# as Docker does; several heredocs on one line close in order; `<<<` (a here-string) opens none.
instructions() {
  awk '
    n > 0 {
      line = $0
      if (dash[1]) sub(/^\t+/, "", line)
      if (line == word[1]) { for (i = 1; i < n; i++) { word[i] = word[i + 1]; dash[i] = dash[i + 1] }; n-- }
      next
    }
    {
      print
      rest = $0
      while (match(rest, /(^|[^<])<<-?[ \t]*["\047]?[A-Za-z_][A-Za-z0-9_]*["\047]?/)) {
        found = substr(rest, RSTART, RLENGTH); rest = substr(rest, RSTART + RLENGTH)
        n++; dash[n] = (found ~ /<<-/)
        sub(/^[^<]*<<-?[ \t]*["\047]?/, "", found); sub(/["\047]$/, "", found); word[n] = found
      }
    }' "$1"
}
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
done < <(instructions "$DOCKERFILE" | grep -iE '^[[:space:]]*FROM[[:space:]]')
if [ "$seen" -eq 0 ]; then echo "::error file=${DOCKERFILE}::no FROM line"; exit 1; fi
exit $bad
