"""`python -m cloud_crawler_appliance`: uvicorn on 0.0.0.0:$PORT, no access log, no proxy headers, SIGTERM graceful."""

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
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 # nosec B104 - the container ingress is the only listener in front of this port
        port=settings.port,
        access_log=False,
        proxy_headers=False,
        server_header=False,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
