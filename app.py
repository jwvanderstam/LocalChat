
"""LocalChat application entry point.

Production (Docker / Uvicorn)::

    uvicorn "app:create_uvicorn_app" --factory --host 0.0.0.0 --port 5000

Development::

    python app.py
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

# Add src to path if running from root
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def create_uvicorn_app():
    """Entry point for Uvicorn / ASGI servers (FastAPI).

    Used by the Dockerfile CMD and ``python app.py``.
    """
    from src.app_bootstrap import bootstrap_app
    from src.app_fastapi import create_app

    fastapi_app = create_app()
    bootstrap_app(fastapi_app)
    return fastapi_app


def _is_db_reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _ensure_db_running() -> None:
    from src.config import PG_HOST, PG_PORT

    if _is_db_reachable(PG_HOST, PG_PORT):
        return

    logger.info("PostgreSQL not reachable — starting db service via docker compose...")
    try:
        subprocess.run(
            ["docker", "compose", "up", "-d", "db"],
            check=True,
        )
    except FileNotFoundError:
        logger.error("docker not found — start PostgreSQL manually and retry.")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        logger.error(f"docker compose up db failed (exit {e.returncode})")
        sys.exit(1)

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if _is_db_reachable(PG_HOST, PG_PORT):
            logger.info("PostgreSQL is up.")
            return
        time.sleep(1)

    logger.error("PostgreSQL did not become reachable within 30 s — aborting.")
    sys.exit(1)


def main() -> None:
    """Run the FastAPI app via Uvicorn (development entry point)."""
    import uvicorn

    _ensure_db_running()

    HOST = os.environ.get("SERVER_HOST", "localhost")
    try:
        PORT = int(os.environ.get("SERVER_PORT", "5000"))
    except ValueError:
        PORT = 5000

    logger.info("Starting LocalChat on http://%s:%d", HOST, PORT)
    try:
        uvicorn.run(
            "app:create_uvicorn_app",
            factory=True,
            host=HOST,
            port=PORT,
            log_level="info",
            reload=False,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down.")
    except Exception as exc:
        logger.error("Server error: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
