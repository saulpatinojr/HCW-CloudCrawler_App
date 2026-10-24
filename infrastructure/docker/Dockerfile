# Cloud Crawler App edition: the appliance image. One stage installs the hash-pinned runtime set and copies the engine
# and the application as source trees (no build backend enters the image); the final stage runs as uid 10001 with pip
# removed and /tmp the only writable path. Every FROM is the digest in infrastructure/docker/versions.env.
#
# Build:  docker build -f infrastructure/docker/Dockerfile -t hcw-cloud-crawler-appliance:dev .
# Prove:  docker run --rm -e AZURE_CLIENT_SECRET=x hcw-cloud-crawler-appliance:dev   # exit 3: refused
#         docker run --rm -p 8080:8080 hcw-cloud-crawler-appliance:dev               # GET /api/health answers

FROM python:3.14.8-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS deps
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /build
COPY requirements.lock.txt ./
RUN pip install --require-hashes --no-deps --prefix /install -r requirements.lock.txt
COPY packages/cloud-crawler-core/src/cloud_crawler_core /install/lib/python3.14/site-packages/cloud_crawler_core
COPY src/cloud_crawler_appliance /install/lib/python3.14/site-packages/cloud_crawler_appliance
RUN find /install -name "__pycache__" -type d -prune -exec rm -rf {} + \
 && python - <<'PY'
import importlib.util, sys
sys.path.insert(0, "/install/lib/python3.14/site-packages")
import cloud_crawler_core, cloud_crawler_appliance  # noqa: F401
for forbidden in ("azure", "msal", "boto3"):
    if importlib.util.find_spec(forbidden) is not None:
        raise SystemExit(f"this slice carries no cloud SDK; {forbidden} is importable")
print("image contents verified: engine and appliance import; no cloud SDK")
PY

FROM python:3.14.8-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS appliance
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 CC_BIND_HOST=0.0.0.0
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* \
 && (python -m pip uninstall -y pip setuptools wheel >/dev/null 2>&1 || true) \
 && rm -rf /usr/local/lib/python3.14/ensurepip /usr/local/lib/python3.14/site-packages/pip* \
           /usr/local/lib/python3.14/site-packages/setuptools* /usr/local/lib/python3.14/site-packages/wheel* \
           /usr/local/bin/pip* /usr/local/bin/wheel /root/.cache \
 && groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=deps /install /usr/local
WORKDIR /app
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '8080'), timeout=3).status==200 else 1)"]
CMD ["python", "-m", "cloud_crawler_appliance"]
