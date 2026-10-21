"""The application factory: a flat /api/health, the MCP endpoint at /mcp (streamable HTTP, stateless), the error
envelope for every other /api path, and no-store on everything under /api."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

from cloud_crawler_core import __version__ as engine_version
from cloud_crawler_core.detectors import DETECTORS
from cloud_crawler_core.ledger import InMemoryLedger
from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse
from mcp.server.transport_security import TransportSecuritySettings

from cloud_crawler_appliance import ADDON_ID, __version__
from cloud_crawler_appliance.config import Settings
from cloud_crawler_appliance.edition import AZURE_CONNECTIVITY, CAPABILITIES, EDITION, refuse_forbidden_env
from cloud_crawler_appliance.mcp_server import build_mcp_server
from cloud_crawler_appliance.security import logging as logs

MCP_PATH = "/mcp"
MCP_PROTOCOL_VERSION = "2026-07-28"


def _envelope(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def create_app(settings: Settings | None = None, *, ledger: InMemoryLedger | None = None, env=None) -> FastAPI:
    settings = settings or Settings.from_env(env)
    refuse_forbidden_env(env)
    logs.configure(silent=settings.log_silent)
    ledger = ledger if ledger is not None else InMemoryLedger()
    mcp = build_mcp_server(ledger, max_rows=settings.max_rows)
    transport_security = (
        TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=list(settings.allowed_hosts))
        if settings.allowed_hosts
        else None  # the SDK's default: loopback hosts only
    )
    mcp_app = mcp.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        max_request_body_size=settings.max_upload_bytes,
        transport_security=transport_security,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logs.log_event("startup", detectors=len(DETECTORS))
        async with mcp_app.router.lifespan_context(mcp_app):
            yield
        logs.log_event("shutdown")

    app = FastAPI(
        title="Cloud Crawler", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.ledger = ledger

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "id": ADDON_ID,
            "version": __version__,
            "edition": EDITION,
            "capabilities": list(CAPABILITIES),
            "asOf": _now_iso(),
            "azureConnectivity": AZURE_CONNECTIVITY,
            "engine": {"name": "cloud-crawler-core", "version": engine_version, "detectors": sorted(DETECTORS)},
            "mcp": {"path": MCP_PATH, "protocolVersion": MCP_PROTOCOL_VERSION, "stateless": True},
            "ledger": {
                "decisions": len(ledger.decisions),
                "evidence": len(ledger.evidence),
                "openContradictions": len(ledger.open_contradictions()),
                "openProposals": len(ledger.open_proposals()),
            },
            "limits": {
                "maxUploadBytes": settings.max_upload_bytes,
                "maxRows": settings.max_rows,
                "evidenceTtlHours": settings.evidence_ttl_hours,
            },
            "production": False,
        }

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    def api_catch_all(rest: str) -> JSONResponse:
        if rest == "health":
            return _envelope(405, "method_not_allowed", "GET only")
        return _envelope(404, "not_found", "no such route")

    @app.exception_handler(HTTPException)
    async def http_exception(_: Request, exc: HTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "error")
        return _envelope(exc.status_code, code, str(exc.detail) if exc.status_code < 500 else "error")

    @app.exception_handler(RequestValidationError)
    async def validation_exception(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope(422, "invalid_request", "request did not validate")

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        logs.log_exception("unhandled_error", exc)
        return _envelope(500, "internal_error", "internal error")

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    app.mount("/", mcp_app)
    return app
