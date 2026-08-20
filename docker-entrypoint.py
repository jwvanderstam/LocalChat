"""Expand the runtime environment variables a shell would have expanded.

The hardened base image ships no shell, so the previous `sh -c` CMD — and the
`${SERVER_PORT:-5000}` style defaults inside it — cannot run. This does that job
in Python and then `exec`s uvicorn in place, so the server stays PID 1 and
signals reach it unchanged.
"""

from __future__ import annotations

import os
import sys
import urllib.request


def _port() -> str:
    return os.getenv("SERVER_PORT", "5000")


def healthcheck() -> None:
    """HEALTHCHECK target. Must agree with main() about the port, which is why
    it lives here rather than as a hardcoded URL in the Dockerfile."""
    urllib.request.urlopen(f"http://localhost:{_port()}/api/health", timeout=5)


def main() -> None:
    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "app:create_uvicorn_app",
            "--factory",
            "--host", os.getenv("SERVER_HOST", "0.0.0.0"),
            "--port", _port(),
            "--workers", os.getenv("UVICORN_WORKERS", "1"),
            "--timeout-keep-alive", os.getenv("UVICORN_TIMEOUT", "600"),
            "--log-level", "info",
            # Who may set X-Forwarded-For is decided once, by TRUSTED_PROXY_IPS
            # in src/config.py. Uvicorn's own default (127.0.0.1) is a second
            # answer to the same question, and two of those is what let the
            # header be silently ignored behind the nginx overlay.
            "--forwarded-allow-ips", "",
        ],
    )


if __name__ == "__main__":
    if "--healthcheck" in sys.argv:
        healthcheck()
    else:
        main()
