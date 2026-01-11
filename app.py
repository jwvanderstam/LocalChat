# -*- coding: utf-8 -*-

"""
Flask Application Launcher
==========================

Main entry point for LocalChat RAG application.
Uses application factory pattern for better testability.

Example:
    >>> python app.py
    # Starts web server on http://localhost:5000

Author: LocalChat Team
Last Updated: 2025-01-15 (Refactored to use application factory)
"""

import os
import sys
from pathlib import Path

# Add src to path if running from root
sys.path.insert(0, str(Path(__file__).parent))

from src.app_factory import create_app
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def main():
    """
    Main application entry point.
    
    Creates and runs the Flask application using the factory pattern.
    """
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
    logger.info(f"Ollama: {'?' if app.startup_status['ollama'] else '?'}")
    logger.info(f"Database: {'?' if app.startup_status['database'] else '?'}")
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
