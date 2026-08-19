"""Expand the runtime environment variables a shell would have expanded.

The hardened base image ships no shell, so the previous `sh -c` CMD — and the
`${SERVER_PORT:-5000}` style defaults inside it — cannot run. This does that job
in Python and then `exec`s uvicorn in place, so the server stays PID 1 and
signals reach it unchanged.
"""

from __future__ import annotations

import os


def main() -> None:
    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "app:create_uvicorn_app",
            "--factory",
            "--host", os.getenv("SERVER_HOST", "0.0.0.0"),
            "--port", os.getenv("SERVER_PORT", "5000"),
            "--workers", os.getenv("UVICORN_WORKERS", "1"),
            "--timeout-keep-alive", os.getenv("UVICORN_TIMEOUT", "600"),
            "--log-level", "info",
        ],
    )


if __name__ == "__main__":
    main()
