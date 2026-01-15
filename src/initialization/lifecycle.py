# -*- coding: utf-8 -*-

"""
Application Lifecycle Management
================================

Handles application startup checks, cleanup, and signal handling.

This module provides:
- startup_checks(): Verifies Ollama and database availability
- cleanup(): Closes connections and cleans up resources
- signal_handler(): Handles shutdown signals gracefully
- register_lifecycle_handlers(): Registers all lifecycle callbacks

Author: LocalChat Team
Created: January 2025
"""

import sys
import signal
import atexit
from typing import Any

from ..utils.logging_config import get_logger
from ..db import db
from ..ollama_client import ollama_client
from .. import config

logger = get_logger(__name__)

# Startup status tracking
startup_status = {
    'ollama': False,
    'database': False,
    'ready': False
}


def startup_checks() -> None:
    """
    Perform startup checks for Ollama and database.
    
    Verifies that required services (Ollama, PostgreSQL) are available
    and initializes the application state.
    
    ENHANCED: Exits immediately with clear error if database is unavailable.
    """
    logger.info("=" * 50)
    logger.info("Starting LocalChat Application")
    logger.info("=" * 50)
    
    # Check Ollama
    logger.info("1. Checking Ollama...")
    ollama_success, ollama_message = ollama_client.check_connection()
    startup_status['ollama'] = ollama_success
    
    if ollama_success:
        logger.info(f"? {ollama_message}")
    else:
        logger.error(f"? {ollama_message}")
    
    if ollama_success:
        # Load first available model if no active model set
        if not config.app_state.get_active_model():
            first_model = ollama_client.get_first_available_model()
            if first_model:
                config.app_state.set_active_model(first_model)
                logger.info(f"? Active model set to: {first_model}")
    
    # Check Database
    logger.info("2. Checking PostgreSQL with pgvector...")
    db_success, db_message = db.initialize()
    startup_status['database'] = db_success
    
    if db_success:
        logger.info(f"? {db_message}")
        doc_count = db.get_document_count()
        config.app_state.set_document_count(doc_count)
        logger.info(f"? Documents in database: {doc_count}")
    else:
        logger.error(f"? {db_message}")
        logger.error("=" * 50)
        logger.error("? CRITICAL: PostgreSQL database is not available!")
        logger.error("=" * 50)
        logger.error("\n" + db_message + "\n")
        logger.error("Application cannot start without database connectivity.")
        logger.error("=" * 50)
        # Exit immediately with clear error code
        sys.exit(1)
    
    # Overall status
    startup_status['ready'] = startup_status['ollama'] and startup_status['database']
    
    logger.info("3. Starting web server...")
    if startup_status['ready']:
        logger.info("? All services ready!")
        logger.info("? Server starting on http://localhost:5000")
    else:
        logger.warning("? Some services are not available")
        logger.warning("? Server starting with limited functionality")
    
    logger.info("=" * 50)


def cleanup() -> None:
    """
    Cleanup function to close database connections.
    
    Called automatically on application shutdown to ensure
    all connections are properly closed.
    """
    if db.is_connected:
        logger.info("Closing database connections...")
        db.close()
        logger.info("Cleanup complete")


def signal_handler(sig: int, frame: Any) -> None:
    """
    Handle interrupt signals gracefully.
    
    Args:
        sig: Signal number
        frame: Current stack frame
    """
    logger.info("\nReceived interrupt signal, shutting down...")
    cleanup()
    logger.info("Goodbye!")
    sys.exit(0)


def register_lifecycle_handlers() -> None:
    """
    Register all lifecycle handlers.
    
    Sets up:
    - Atexit cleanup handler
    - SIGINT signal handler (Ctrl+C)
    - SIGTERM signal handler (kill)
    """
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    logger.debug("Lifecycle handlers registered")
