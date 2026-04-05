
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
import sys
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


def _print_db_unavailable_warning() -> None:
    """Print a prominent console warning when PostgreSQL is not available at startup."""
    border = "=" * 60
    print("", file=sys.stderr)
    print(border, file=sys.stderr)
    print("  WARNING: PostgreSQL database is NOT available", file=sys.stderr)
    print(border, file=sys.stderr)
    print("  LocalChat is running in DEGRADED MODE:", file=sys.stderr)
    print("    - Document storage and retrieval are disabled", file=sys.stderr)
    print("    - Conversation history will not be persisted", file=sys.stderr)
    print("    - RAG features are unavailable", file=sys.stderr)
    print("", file=sys.stderr)
    print("  To resolve this, ensure:", file=sys.stderr)
    print("    1. PostgreSQL is installed and running", file=sys.stderr)
    print("    2. The database host/port in config.py are correct", file=sys.stderr)
    print("    3. The database credentials are correct", file=sys.stderr)
    print("", file=sys.stderr)
    print("  Set REQUIRE_DATABASE=true to abort startup instead.", file=sys.stderr)
    print(border, file=sys.stderr)
    print("", file=sys.stderr)


def main():
    """
    Main application entry point.

    Creates and runs the Flask application using the factory pattern.
    """
    # Create application
    app = create_app()

    # Warn the user prominently if the database is unavailable
    if not app.startup_status.get('database', False):
        _print_db_unavailable_warning()

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
