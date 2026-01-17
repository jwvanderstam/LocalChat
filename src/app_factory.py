# -*- coding: utf-8 -*-

"""
Application Factory Module
==========================

Flask application factory for LocalChat RAG application.
Implements dependency injection and configurable app creation for better testability.

Features:
    - Application factory pattern
    - Dependency injection
    - Configurable testing/production modes
    - Blueprint registration
    - Error handler setup
    - Middleware initialization

Example:
    >>> from src.app_factory import create_app
    >>> app = create_app()
    >>> app.run()

Author: LocalChat Team
Created: 2025-01-15
"""

from flask import Flask
from pathlib import Path
from typing import Optional, Dict, Any
import os

from . import config
from .utils.logging_config import setup_logging, get_logger

# Setup logger
logger = get_logger(__name__)


def create_app(
    config_override: Optional[Dict[str, Any]] = None,
    testing: bool = False
) -> Flask:
    """
    Create and configure Flask application instance.
    
    Implements the application factory pattern for better testability
    and separation of concerns. Allows dependency injection of services
    and configuration overrides for different environments.
    
    Args:
        config_override: Dictionary of configuration values to override defaults
        testing: If True, configure app for testing mode
    
    Returns:
        Configured Flask application instance
    
    Example:
        >>> # Production
        >>> app = create_app()
        >>> 
        >>> # Testing
        >>> test_config = {'TESTING': True, 'DATABASE_URL': 'sqlite:///:memory:'}
        >>> app = create_app(config_override=test_config, testing=True)
    """
    # Get root directory
    root_dir = Path(__file__).parent.parent
    
    # Create Flask app
    app = Flask(
        __name__,
        template_folder=str(root_dir / 'templates'),
        static_folder=str(root_dir / 'static')
    )
    
    # Load configuration
    _load_configuration(app, config_override, testing)
    
    # Initialize logging
    if not testing:
        log_level = "DEBUG" if app.config.get('DEBUG', False) else "INFO"
        setup_logging(log_level=log_level, log_file="logs/app.log")
    
    # Initialize extensions and services
    _init_services(app, testing)
    
    # Initialize API documentation (Swagger/OpenAPI)
    if not testing:
        _init_api_docs(app)
    
    # Initialize monitoring and metrics
    if not testing:
        _init_monitoring(app)
    
    # Register blueprints
    _register_blueprints(app)
    
    # Register error handlers
    _register_error_handlers(app)
    
    # Initialize security middleware
    _init_security(app, testing)
    
    # Setup cleanup handlers
    _setup_cleanup_handlers(app)
    
    logger.info(f"Flask application created (testing={testing})")
    
    return app


def _load_configuration(
    app: Flask,
    config_override: Optional[Dict[str, Any]],
    testing: bool
) -> None:
    """
    Load application configuration.
    
    Args:
        app: Flask application instance
        config_override: Configuration overrides
        testing: Testing mode flag
    """
    # Base configuration from config module
    app.config['SECRET_KEY'] = config.SECRET_KEY
    app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
    app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
    
    # Testing configuration
    if testing:
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['DEBUG'] = False
    
    # Apply overrides
    if config_override:
        app.config.update(config_override)
    
    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    logger.debug(f"Configuration loaded (testing={testing})")


def _init_services(app: Flask, testing: bool) -> None:
    """
    Initialize application services and dependencies.
    
    Args:
        app: Flask application instance
        testing: Testing mode flag
    """
    # Import services
    from .db import db
    from .ollama_client import ollama_client
    from .rag import doc_processor
    
    # Store services in app context for dependency injection
    app.db = db
    app.ollama_client = ollama_client
    app.doc_processor = doc_processor
    
    # Initialize caching
    _init_caching(app, testing)
    
    # Initialize global startup status
    app.startup_status = {
        'ollama': False,
        'database': False,
        'ready': False
    }
    
    # Don't initialize services in testing mode
    if not testing:
        # Check Ollama
        logger.info("Checking Ollama connection...")
        ollama_success, ollama_message = ollama_client.check_connection()
        app.startup_status['ollama'] = ollama_success
        
        if ollama_success:
            logger.info(f"? {ollama_message}")
            # Load first available model
            if not config.app_state.get_active_model():
                first_model = ollama_client.get_first_available_model()
                if first_model:
                    config.app_state.set_active_model(first_model)
                    logger.info(f"? Active model set to: {first_model}")
        else:
            logger.warning(f"? {ollama_message}")
        
        # Check Database
        logger.info("Checking PostgreSQL with pgvector...")
        db_success, db_message = db.initialize()
        app.startup_status['database'] = db_success
        
        if db_success:
            logger.info(f"? {db_message}")
            doc_count = db.get_document_count()
            config.app_state.set_document_count(doc_count)
            logger.info(f"? Documents in database: {doc_count}")
        else:
            logger.error(f"? {db_message}")
            logger.error("=" * 50)
            logger.error("? WARNING: PostgreSQL database is not available!")
            logger.error("? App will run in DEGRADED MODE (no document storage)")
            logger.error("=" * 50)
            
            # Check if we're in strict production mode (require DB)
            strict_mode = os.environ.get('REQUIRE_DATABASE', 'false').lower() == 'true'
            
            if strict_mode:
                logger.critical("? REQUIRE_DATABASE=true - cannot start without database")
                import sys
                sys.exit(1)
            else:
                logger.warning("? Continuing without database (development mode)")
        
        # Set overall ready status
        app.startup_status['ready'] = (
            app.startup_status['ollama'] and app.startup_status['database']
        )
    
    logger.debug("Services initialized")


def _init_caching(app: Flask, testing: bool) -> None:
    """
    Initialize caching layer.
    
    Args:
        app: Flask application instance
        testing: Testing mode flag
    """
    try:
        from .cache import create_cache_backend
        from .cache.managers import init_caches
        import os
        
        # Check if Redis is enabled
        redis_enabled = os.environ.get('REDIS_ENABLED', 'False').lower() == 'true'
        
        # Prepare backend configuration
        if redis_enabled:
            cache_backend_type = 'redis'
            backend_config = {
                'host': os.environ.get('REDIS_HOST', 'localhost'),
                'port': int(os.environ.get('REDIS_PORT', 6379)),
                'password': os.environ.get('REDIS_PASSWORD') or None
            }
        else:
            cache_backend_type = 'memory'
            backend_config = {
                'max_size': 5000  # Only for memory cache
            }
        
        # Create embedding backend
        embedding_backend = create_cache_backend(
            cache_backend_type,
            namespace='embeddings',
            **backend_config
        )
        
        # Create query backend (different max_size for memory)
        if cache_backend_type == 'memory':
            backend_config['max_size'] = 1000
        
        query_backend = create_cache_backend(
            cache_backend_type,
            namespace='queries',
            **backend_config
        )
        
        # Initialize cache managers
        embedding_cache, query_cache = init_caches(
            embedding_backend=embedding_backend,
            query_backend=query_backend,
            embedding_ttl=3600 * 24 * 7,  # 7 days
            query_ttl=3600  # 1 hour
        )
        
        # Attach to app
        app.embedding_cache = embedding_cache
        app.query_cache = query_cache
        
        backend_name = type(embedding_backend).__name__
        logger.info(f"? Caching initialized ({backend_name})")
        
    except Exception as e:
        logger.warning(f"??  Caching initialization failed: {e}")
        logger.warning("??  Running without cache (will impact performance)")
        app.embedding_cache = None
        app.query_cache = None


def _register_blueprints(app: Flask) -> None:
    """
    Register Flask blueprints for modular routing.
    
    Args:
        app: Flask application instance
    """
    # Import blueprints
    from .routes import web_routes, api_routes, document_routes, model_routes
    
    # Register blueprints
    app.register_blueprint(web_routes.bp)
    app.register_blueprint(api_routes.bp, url_prefix='/api')
    app.register_blueprint(document_routes.bp, url_prefix='/api/documents')
    app.register_blueprint(model_routes.bp, url_prefix='/api/models')
    
    logger.debug("Blueprints registered")


def _register_error_handlers(app: Flask) -> None:
    """
    Register application error handlers.
    
    Args:
        app: Flask application instance
    """
    from .routes import error_handlers
    
    # Register error handlers
    error_handlers.register_error_handlers(app)
    
    logger.debug("Error handlers registered")


def _init_security(app: Flask, testing: bool) -> None:
    """
    Initialize security middleware.
    
    Args:
        app: Flask application instance
        testing: Testing mode flag
    """
    # Skip security in testing mode
    if testing:
        app.security_enabled = False
        return
    
    try:
        from . import security
        
        # Initialize security features
        security.init_security(app)
        security.setup_auth_routes(app)
        security.setup_health_check(app)
        security.setup_rate_limit_handler(app)
        
        app.security_enabled = True
        logger.info("? Security middleware initialized")
        
    except ImportError as e:
        app.security_enabled = False
        logger.warning(f"??  Security middleware not available: {e}")


def _setup_cleanup_handlers(app: Flask) -> None:
"""
Setup application cleanup handlers.
    
Args:
    app: Flask application instance
"""
import atexit
import signal
    
# Flag to prevent duplicate cleanup
_cleanup_done = {'done': False}
    
def cleanup() -> None:
    """Cleanup function to close database connections."""
    # Prevent duplicate cleanup
    if _cleanup_done['done']:
        return
    _cleanup_done['done'] = True
        
    try:
        if hasattr(app, 'db') and app.db and hasattr(app.db, 'is_connected') and app.db.is_connected:
            logger.info("Closing database connections...")
            app.db.close()
            logger.info("Cleanup complete")
    except Exception as e:
        # Silently handle cleanup errors during shutdown
        pass
    
def signal_handler(sig: int, frame: Any) -> None:
    """Handle interrupt signals gracefully."""
    try:
        logger.info("\nReceived interrupt signal, shutting down...")
        cleanup()
        logger.info("Goodbye!")
    except Exception:
        # Silently handle errors during signal handling
        pass
    finally:
        import sys
        sys.exit(0)
    
# Register cleanup handlers
atexit.register(cleanup)
    
# Only register signal handlers if not in debugger
try:
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
except (ValueError, OSError):
    # Signal registration may fail in some environments (e.g., debugger)
    pass
    
logger.debug("Cleanup handlers registered")


def _init_api_docs(app: Flask) -> None:
    """
    Initialize API documentation (Swagger/OpenAPI).
    
    Args:
        app: Flask application instance
    """
    try:
        from .api_docs import init_swagger
        
        swagger = init_swagger(app)
        app.swagger = swagger
        
        logger.info("? API documentation initialized at /api/docs/")
        
    except ImportError as e:
        logger.warning(f"??  API documentation not available: {e}")
    except Exception as e:
        logger.error(f"Error initializing API docs: {e}", exc_info=True)


def _init_monitoring(app: Flask) -> None:
    """
    Initialize monitoring and metrics.
    
    Args:
        app: Flask application instance
    """
    try:
        from .monitoring import init_monitoring
        
        init_monitoring(app)
        
        logger.info("? Monitoring initialized at /api/metrics and /api/health")
        
    except Exception as e:
        logger.error(f"Error initializing monitoring: {e}", exc_info=True)


# Export for backward compatibility
__all__ = ['create_app']
