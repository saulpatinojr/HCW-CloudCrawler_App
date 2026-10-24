"""`python -m cloud_crawler_appliance`: uvicorn on $CC_BIND_HOST:$PORT (loopback unless the deployment says otherwise;
the container image sets 0.0.0.0), no access log, no proxy headers, SIGTERM graceful."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from cloud_crawler_appliance.api import create_app
        from cloud_crawler_appliance.config import Settings
        from cloud_crawler_appliance.edition import assert_appliance_ready

        assert_appliance_ready()
        settings = Settings.from_env()
        app = create_app(settings)
    except Exception as exc:  # noqa: BLE001 - startup refusal is the point; the reason is printed once, scrubbed
        import json

        from cloud_crawler_core.redaction import scrub

        reason = scrub(f"{type(exc).__name__}: {exc}")
        sys.stderr.write(json.dumps({"event": "startup_refused", "reason": reason}) + "\n")
        return 3
    import ipaddress

    import uvicorn

    from cloud_crawler_appliance.security import logging as logs

    if settings.auth_mode == "off" and not ipaddress.ip_address(settings.bind_host).is_loopback:
        # Not a refusal (the lab image runs this way); said once so an exposed, unauthenticated server is not silent.
        logs.log_event("warning", auth=False, exposed=True)
    uvicorn.run(
        app,
        host=settings.bind_host,  # nosec B104 - 0.0.0.0 only when CC_BIND_HOST says so (the image); else loopback
        port=settings.port,
        access_log=False,
        proxy_headers=False,
        server_header=False,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
