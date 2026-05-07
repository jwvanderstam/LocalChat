
"""
Flask Application Launcher
==========================

Main entry point for LocalChat RAG application.
Uses application factory pattern for better testability.

Example:
    >>> python app.py
    # Starts web server on http://localhost:5000

Author: LocalChat Team
Last Updated: 2026-03-15 (Refactored to use application factory)
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

# Add src to path if running from root
sys.path.insert(0, str(Path(__file__).parent))

from src.app_factory import create_app
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def create_gunicorn_app():
    """
    Entry point for Gunicorn / WSGI servers.

    Usage in Dockerfile CMD::

        gunicorn "app:create_gunicorn_app()"

    Returns:
        Configured Flask application instance.
    """
    return create_app()


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


def main():
    """
    Main application entry point.

    Creates and runs the Flask application using the factory pattern.
    """
    _ensure_db_running()

    # Create application
    app = create_app()

    # Get configuration from environment
    HOST = os.environ.get('SERVER_HOST', 'localhost')
    try:
        PORT = int(os.environ.get('SERVER_PORT', '5000'))
    except ValueError:
        PORT = 5000

    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

    logger.info("=" * 50)
    logger.info("LocalChat Application Ready")
    logger.info("=" * 50)
    logger.info(f"Server: http://{HOST}:{PORT}")
    logger.info(f"Debug: {DEBUG}")
    logger.info(f"Ollama: {'OK' if app.startup_status['ollama'] else 'UNAVAILABLE'}")
    logger.info(f"Database: {'OK' if app.startup_status['database'] else 'UNAVAILABLE'}")
    logger.info("=" * 50)

    # Run application
    try:
        app.run(
            host=HOST,
            port=PORT,
            debug=DEBUG,
            use_reloader=False  # Disable reloader to avoid double cleanup
        )
    except KeyboardInterrupt:
        logger.info("\nShutting down gracefully...")
    except Exception as e:
        logger.error(f"Error starting server: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
