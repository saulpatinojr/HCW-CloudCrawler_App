#!/usr/bin/env bash
# Scan the appliance image for known vulnerabilities with Trivy. The weekly workflow (.github/workflows/image-scan.yml)
# and a person at a keyboard run this same file, so what you see here is what CI enforces (ticket #15).
#
# What it needs: Docker and bash. On Windows that is Docker Desktop (Linux containers, context `desktop-linux`) and Git
# Bash; from PowerShell run `bash scripts/scan-image.sh`. Nothing else is installed.
#
# Usage:   bash scripts/scan-image.sh [IMAGE]
#   With no argument it builds infrastructure/docker/Dockerfile as hcw-cloud-crawler-appliance:scan, scans it and removes
#   that tag again. With IMAGE it scans an image that is already in the local image store and removes nothing.
#
# Two passes, both against the same exported image:
#   1. The gate. HIGH and CRITICAL findings that have a fix available (--ignore-unfixed) fail the run (exit 1), unless an
#      unexpired entry in .trivyignore.yaml accepts them. This is the pass that says "update the base image now".
#   2. The register check. Every HIGH and CRITICAL finding that .trivyignore.yaml does not accept is listed and
#      reported as a warning (when pass 1 passed, none of them has a fix yet). It does not fail the run; it asks the
#      owner to decide and add an entry (with a reason, an owner and an expiry date) or to act. An entry past its
#      expiry stops hiding its finding, so it shows up here (or in the gate, if a fix exists by then) until it is
#      renewed.
#
# How it stays safe: Trivy runs in a disposable container (--rm) with a read-only root file system, all capabilities
# dropped, no privilege escalation, no Docker socket, and your own user id instead of root. The image is exported to a
# temporary tar file that is mounted read-only; the accepted-risk file is mounted read-only; the only writable places
# are a tmpfs and a temporary cache folder for the vulnerability database. Trivy needs network access to download that
# database. Everything it creates is deleted when the script ends.
#
# Locally the script stops when `docker context show` names an engine other than your own machine (desktop-linux, or
# default on Linux), or when DOCKER_HOST is set, because scanning against a shared or remote engine is a different
# decision. Set CC_SCAN_ANY_CONTEXT=1 only when you mean it. In GitHub Actions (CI=true) the check is skipped.
#
# Where the Trivy version comes from: the newest stable release on the date in the comment, taken from
# https://github.com/aquasecurity/trivy/releases/latest, pulled by tag, and pinned by the index digest the registry
# reported (`docker buildx imagetools inspect ghcr.io/aquasecurity/trivy:<tag>`). Never use a tag alone and never
# `latest`: on 2026-03-19 and 2026-03-22 malicious Trivy images were published under moving tags
# (GHSA-69fq-xp46-6x23); a digest cannot be moved. 0.72.0 or later is required for the plugin path-traversal fix.
# To move the pin: resolve the new digest the same way, change the line below, and update the expected value in
# tests/unit/test_image_scan.py in the same pull request.

set -euo pipefail

# Trivy 0.76.1 (released 2026-10-21) https://github.com/aquasecurity/trivy/releases/tag/v0.76.1
TRIVY_IMAGE="ghcr.io/aquasecurity/trivy:0.76.1@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c"
BUILT_TAG="hcw-cloud-crawler-appliance:scan"
IGNORE_FILE=".trivyignore.yaml"
SEVERITY="HIGH,CRITICAL"

# Git Bash rewrites paths that look like Unix paths before handing them to docker.exe; switch that off, and use the
# Windows form of every path (pwd -W exists only in Git Bash) so Docker Desktop can mount it.
export MSYS_NO_PATHCONV=1
cd "$(dirname "${BASH_SOURCE[0]}")/.."
host_path() { (cd "$1" && { pwd -W 2>/dev/null || pwd; }); }
REPO="$(host_path .)"

say() { printf '%s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }

command -v docker >/dev/null 2>&1 || fail "docker was not found on PATH. Start Docker Desktop and try again."
[ -f "$IGNORE_FILE" ] || fail "$IGNORE_FILE is missing; the accepted-risk file must exist (it may list no entries)."
if [ "${CI:-}" != "true" ] && [ "${CC_SCAN_ANY_CONTEXT:-0}" != "1" ]; then
  context="$(docker context show 2>/dev/null || true)"
  case "$context" in
    desktop-linux | default) ;;
    *) fail "Docker context '$context' is not desktop-linux or default. Switch with 'docker context use desktop-linux', or set CC_SCAN_ANY_CONTEXT=1 if you really mean this engine." ;;
  esac
  [ -z "${DOCKER_HOST:-}" ] || fail "DOCKER_HOST is set ($DOCKER_HOST); unset it, or set CC_SCAN_ANY_CONTEXT=1 if you really mean that engine."
fi
docker info >/dev/null 2>&1 || fail "the Docker engine does not answer. Start Docker Desktop and try again."

work="$(mktemp -d)"
built=""
# shellcheck disable=SC2329 # called by the EXIT trap below
cleanup() {
  rm -rf "$work"
  if [ -n "$built" ]; then docker image rm "$built" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

image="${1:-}"
if [ -z "$image" ]; then
  image="$BUILT_TAG"
  say "== building $image from infrastructure/docker/Dockerfile"
  docker build --quiet -f infrastructure/docker/Dockerfile -t "$image" . >/dev/null
  built="$image"
else
  docker image inspect "$image" >/dev/null 2>&1 || fail "image '$image' is not in the local image store"
fi

mkdir "$work/image" "$work/cache"
image_dir="$(host_path "$work/image")"
cache_dir="$(host_path "$work/cache")"
say "== exporting $image to a temporary tar file"
docker save "$image" -o "$image_dir/image.tar"

trivy() {
  docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
    --user "$(id -u):$(id -g)" --tmpfs /tmp -e HOME=/tmp -e TRIVY_CACHE_DIR=/cache \
    -v "$cache_dir:/cache" -v "$image_dir:/scan:ro" -v "$REPO/$IGNORE_FILE:/config/trivyignore.yaml:ro" \
    "$TRIVY_IMAGE" "$@"
}

say "== pass 1, the gate: fixable $SEVERITY findings fail the run"
gate=0
trivy image --no-progress --scanners vuln --input /scan/image.tar --severity "$SEVERITY" --ignore-unfixed \
  --ignorefile /config/trivyignore.yaml --exit-code 1 || gate=$?

say "== pass 2, the register check: $SEVERITY findings that $IGNORE_FILE does not accept"
listing="$work/unregistered.txt"
trivy image --quiet --scanners vuln --input /scan/image.tar --severity "$SEVERITY" --skip-db-update \
  --ignorefile /config/trivyignore.yaml --exit-code 0 --format template \
  --template '{{ range . }}{{ range .Vulnerabilities }}{{ .Severity }} {{ .VulnerabilityID }} {{ .PkgName }} {{ .InstalledVersion }}{{ "\n" }}{{ end }}{{ end }}' \
  >"$listing"
unregistered="$(awk 'NF { print $2 }' "$listing" | sort -u)"
count=0
if [ -n "$unregistered" ]; then count="$(printf '%s\n' "$unregistered" | wc -l | tr -d ' ')"; fi

summary="gate (fixable $SEVERITY, unaccepted): "
if [ "$gate" -eq 0 ]; then summary+="PASS"; else summary+="FAIL (exit $gate)"; fi
summary+=". $SEVERITY vulnerabilities not accepted in $IGNORE_FILE: $count."
say ""
say "$summary"
if [ "$count" -gt 0 ]; then
  say "Not accepted (decide, then add an entry with a reason, an owner and an expiry date, or fix them):"
  sort -u "$listing" | sed 's/^/  /'
  if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    echo "::warning title=Image scan::$count $SEVERITY vulnerability id(s) are not accepted in $IGNORE_FILE; see the log of this step."
  fi
fi
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "### Appliance image scan"
    echo ""
    echo "$summary"
    echo ""
    echo "Scanner: \`$TRIVY_IMAGE\`"
  } >>"$GITHUB_STEP_SUMMARY"
fi
exit "$gate"
