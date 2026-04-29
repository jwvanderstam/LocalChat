
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

"""

import os
from pathlib import Path
from typing import Any

from . import config
from .types import LocalChatApp
from .utils.logging_config import get_logger, setup_logging

# Setup logger
logger = get_logger(__name__)


def create_app(
    config_override: dict[str, Any] | None = None,
    testing: bool = False
) -> LocalChatApp:
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
    app = LocalChatApp(
        __name__,
        template_folder=str(root_dir / 'templates'),
        static_folder=str(root_dir / 'static')
    )

    # Load configuration
    _load_configuration(app, config_override, testing)

    # Initialize logging
    if not testing:
        log_level = "DEBUG" if app.config.get('DEBUG', False) else "INFO"
        setup_logging(log_level=log_level, log_file=config.LOG_FILE, log_format=config.LOG_FORMAT)

    # Initialize extensions and services
    _init_services(app, testing)

    # Attach request-ID middleware (runs before everything else)
    from .utils.request_id import init_request_id
    init_request_id(app)

    # Initialize API documentation (Swagger/OpenAPI)
    if not testing:
        _init_api_docs(app)

    # Initialize monitoring and metrics
    if not testing:
        _init_monitoring(app)

    # Security must be initialized before blueprints so the module-level
    # limiter is bound to the app before @limiter.limit() decorators run.
    _init_security(app, testing)

    # Register blueprints
    _register_blueprints(app)

    # Register error handlers
    _register_error_handlers(app)

    # Setup cleanup handlers
    _setup_cleanup_handlers(app)

    logger.info(f"Flask application created (testing={testing})")

    return app


def _load_configuration(
    app: LocalChatApp,
    config_override: dict[str, Any] | None,
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
        app.config['WTF_CSRF_ENABLED'] = False  # NOSONAR
        app.config['DEBUG'] = False

    # Apply overrides
    if config_override:
        app.config.update(config_override)

    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    logger.debug(f"Configuration loaded (testing={testing})")


def _init_services(app: LocalChatApp, testing: bool) -> None:
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

    # Cloud fallback client (None when disabled or litellm not installed)
    app.cloud_client = _init_cloud_client()

    # Initialize caching
    _init_caching(app)

    # Initialize global startup status
    app.startup_status = {
        'ollama': False,
        'database': False,
        'ready': False
    }

    # Don't initialize services in testing mode
    if not testing:
        _init_ollama_service(app, ollama_client)
        _init_database_service(app, db)
        app.startup_status['ready'] = (
            app.startup_status['ollama'] and app.startup_status['database']
        )
        if app.startup_status['database']:
            _seed_admin_user(db)
        _load_plugins(app)
        _init_connectors(app, db, doc_processor)
        _init_reranker_scheduler(app, db)

    logger.debug("Services initialized")


def _init_cloud_client():
    """Return a LiteLLMClient if CLOUD_FALLBACK_ENABLED, else None."""
    if not config.CLOUD_FALLBACK_ENABLED:
        return None
    if not config.CLOUD_MODEL:
        logger.warning("[CloudFallback] CLOUD_FALLBACK_ENABLED=true but CLOUD_MODEL is not set — disabled")
        return None
    try:
        from .llm_client import LiteLLMClient
        return LiteLLMClient(
            provider=config.CLOUD_PROVIDER,
            api_key=config.CLOUD_API_KEY,
            model=config.CLOUD_MODEL,
        )
    except ImportError as e:
        logger.warning(f"[CloudFallback] {e} — cloud fallback disabled")
        return None
    except Exception as e:
        logger.error(f"[CloudFallback] Failed to initialise LiteLLMClient: {e}", exc_info=True)
        return None


def _init_ollama_service(app: LocalChatApp, ollama_client) -> None:
    """Check Ollama availability and set the active model."""
    from . import config
    logger.info("Checking Ollama connection...")
    ollama_success, ollama_message = ollama_client.check_connection()
    app.startup_status['ollama'] = ollama_success
    if ollama_success:
        logger.info(ollama_message)
        if not config.app_state.get_active_model():
            first_model = ollama_client.get_first_available_model(
                preferred=config.DEFAULT_MODEL
            )
            if first_model:
                config.app_state.set_active_model(first_model)
                logger.info(f"Active model set to: {first_model}")
        _warmup_embedding_model(ollama_client)
    else:
        logger.warning(ollama_message)


def _warmup_embedding_model(ollama_client) -> None:
    """Trigger one embedding call at startup to pre-initialize CUDA kernels.

    Ollama lazily compiles GPU kernels on the first inference call, which adds
    1-2 s of latency that would otherwise be charged to the first user request.
    Running a throwaway embedding here amortises that cost at startup.
    """
    try:
        embedding_model = ollama_client.get_embedding_model()
        if embedding_model:
            logger.info(f"Warming up embedding model: {embedding_model}...")
            success, _ = ollama_client.generate_embedding(embedding_model, "warmup")
            if success:
                logger.info("Embedding model warm-up complete")
            else:
                logger.warning("Embedding model warm-up returned no data (non-fatal)")
    except Exception as e:
        logger.warning(f"Embedding model warm-up failed (non-fatal): {e}")


def _init_database_service(app: LocalChatApp, db) -> None:
    """Initialise the database; abort if REQUIRE_DATABASE is set and DB is unavailable."""
    import sys

    from . import config
    logger.info("Checking PostgreSQL with pgvector...")
    db_success, db_message = db.initialize()
    app.startup_status['database'] = db_success
    if db_success:
        logger.info(db_message)
        doc_count = db.get_document_count()
        config.app_state.set_document_count(doc_count)
        logger.info(f"Documents in database: {doc_count}")
        return
    logger.error(db_message)
    logger.error("WARNING: PostgreSQL database is not available! App will run in DEGRADED MODE.")
    if config.REQUIRE_DATABASE:
        logger.critical("REQUIRE_DATABASE=true - cannot start without database")
        border = "=" * 60
        print(f"\n{border}", file=sys.stderr)
        print("  FATAL: PostgreSQL database is NOT available", file=sys.stderr)
        print(f"  Reason: {db_message.splitlines()[0]}", file=sys.stderr)
        print("  REQUIRE_DATABASE=true is set — aborting startup.", file=sys.stderr)
        print(f"{border}\n", file=sys.stderr)
        sys.exit(1)
    logger.warning("Continuing without database (development mode)")


def _load_plugins(app: LocalChatApp) -> None:
    """Scan the configured plugins directory and load all tool plugins."""
    if not config.PLUGINS_ENABLED:
        logger.info("[PLUGINS] Plugin loading disabled (PLUGINS_ENABLED=false)")
        return

    from pathlib import Path

    from .tools import plugin_loader

    plugins_dir = Path(config.PLUGINS_DIR)
    # Resolve relative paths against the repo root (parent of src/)
    if not plugins_dir.is_absolute():
        plugins_dir = Path(__file__).parent.parent / plugins_dir

    count = plugin_loader.load_all(plugins_dir)
    if count:
        tool_names = [t for p in plugin_loader.list_plugins() for t in p["tools"]]
        logger.info(f"[PLUGINS] {count} plugin(s) loaded — tools: {tool_names}")
    app.plugin_loader = plugin_loader


def _init_reranker_scheduler(app: LocalChatApp, db) -> None:
    """Start a weekly background thread for reranker fine-tuning (opt-in)."""
    if not config.RERANKER_ENABLED:
        return
    try:
        import sentence_transformers  # noqa: F401 — check availability
    except ImportError:
        logger.info("[Reranker] sentence-transformers not installed — scheduler skipped")
        return

    import threading

    _WEEK_SECONDS = 7 * 24 * 3600

    def _weekly_train():
        try:
            from .rag.feedback_pipeline import (
                export_training_pairs,
                finetune_reranker,
                persist_reranker_version,
                promote_model,
            )
            pairs = export_training_pairs(db, days=7)
            if len(pairs) < config.FEEDBACK_FINETUNE_MIN_PAIRS:
                logger.info(f"[Reranker] {len(pairs)} pairs < minimum — skipping weekly fine-tune")
            else:
                result = finetune_reranker(pairs)
                if not result.get('skipped'):
                    version_id = persist_reranker_version(db, result)
                    if version_id and result.get('ndcg_after', 0) > result.get('ndcg_before', 0):
                        promote_model(db, version_id)
                        logger.info("[Reranker] Weekly fine-tune complete — model promoted")
        except Exception as exc:
            logger.error(f"[Reranker] Weekly fine-tune failed: {exc}", exc_info=True)
        finally:
            # Re-schedule
            t = threading.Timer(_WEEK_SECONDS, _weekly_train)
            t.daemon = True
            t.start()
            app._reranker_timer = t  # type: ignore[attr-defined]

    t = threading.Timer(_WEEK_SECONDS, _weekly_train)
    t.daemon = True
    t.start()
    app._reranker_timer = t  # type: ignore[attr-defined]
    logger.info("[Reranker] Weekly fine-tune scheduler started")


def _seed_admin_user(db) -> None:
    """Auto-create the admin DB user on first startup if ADMIN_USERNAME is set."""
    admin_username = config.ADMIN_USERNAME
    admin_password = config.ADMIN_PASSWORD
    if not admin_password:
        return  # No password set; skip seeding
    try:
        if db.count_users() == 0:
            from .db.users import hash_user_password
            db.create_user(
                username=admin_username,
                hashed_password=hash_user_password(admin_password),
                role='admin',
            )
            logger.info(f"[Auth] Admin user '{admin_username}' seeded in users table")
    except Exception as exc:
        logger.warning(f"[Auth] Admin seeding skipped: {exc}")


def _init_connectors(app: LocalChatApp, db, doc_processor) -> None:
    """Load connector instances from DB and start the background sync worker."""
    try:
        from .connectors.registry import connector_registry
        from .connectors.worker import SyncWorker
        connector_registry.load_from_db(db)
        worker = SyncWorker(connector_registry, db, doc_processor)
        worker.start()
        app.sync_worker = worker
        app.connector_registry = connector_registry
        logger.info("[Connectors] Sync worker started")
    except Exception as exc:
        logger.warning(f"[Connectors] Failed to start sync worker: {exc}", exc_info=True)
        app.sync_worker = None
        app.connector_registry = None


def _init_caching(app: LocalChatApp) -> None:
    """
    Initialize caching layer.

    Args:
        app: Flask application instance
    """
    try:
        from .cache import create_cache_backend
        from .cache.managers import init_caches

        if config.REDIS_ENABLED:
            cache_backend_type = 'redis'
            backend_config = {
                'host': config.REDIS_HOST,
                'port': config.REDIS_PORT,
                'password': config.REDIS_PASSWORD,
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
        query_backend_config = dict(backend_config)
        if cache_backend_type == 'memory':
            query_backend_config['max_size'] = 1000

        query_backend = create_cache_backend(
            cache_backend_type,
            namespace='queries',
            **query_backend_config
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
        logger.info(f"Caching initialized ({backend_name})")

    except Exception as e:
        logger.warning(f"[!] Caching initialization failed: {e}")
        logger.warning("[!] Running without cache (will impact performance)")
        app.embedding_cache = None
        app.query_cache = None


def _register_blueprints(app: LocalChatApp) -> None:
    """
    Register Flask blueprints for modular routing.

    Args:
        app: Flask application instance
    """
    # Import blueprints
    from .routes import (
        api_routes,
        auth_routes,
        connector_routes,
        document_routes,
        feedback_routes,
        longterm_memory_routes,
        memory_routes,
        model_routes,
        oauth_routes,
        settings_routes,
        web_routes,
        workspace_routes,
    )

    # Register blueprints
    app.register_blueprint(web_routes.bp)
    app.register_blueprint(api_routes.bp, url_prefix='/api')
    app.register_blueprint(document_routes.bp, url_prefix='/api/documents')
    app.register_blueprint(model_routes.bp, url_prefix='/api/models')
    app.register_blueprint(memory_routes.bp, url_prefix='/api')
    app.register_blueprint(longterm_memory_routes.bp, url_prefix='/api/memory')
    app.register_blueprint(feedback_routes.bp, url_prefix='/api')
    app.register_blueprint(workspace_routes.bp)
    app.register_blueprint(connector_routes.bp)
    app.register_blueprint(settings_routes.bp)
    app.register_blueprint(auth_routes.bp, url_prefix='/api')
    app.register_blueprint(oauth_routes.bp, url_prefix='/api')

    logger.debug("Blueprints registered")


def _register_error_handlers(app: LocalChatApp) -> None:
    """
    Register application error handlers.

    Args:
        app: Flask application instance
    """
    from .routes import error_handlers

    # Register error handlers
    error_handlers.register_error_handlers(app)

    logger.debug("Error handlers registered")


def _init_security(app: LocalChatApp, testing: bool) -> None:
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
        logger.info("Security middleware initialized")

    except ImportError as e:
        app.security_enabled = False
        logger.warning(f"[!] Security middleware not available: {e}")


def _setup_cleanup_handlers(app: LocalChatApp) -> None:
    """
    Setup application cleanup handlers.

    Args:
        app: Flask application instance
    """
    import atexit
    import signal

    def cleanup() -> None:
        """Cleanup function to close database connections and stop background workers."""
        if hasattr(app, 'sync_worker') and app.sync_worker is not None:
            logger.info("Stopping connector sync worker...")
            app.sync_worker.stop()
        if hasattr(app, 'db') and app.db.is_connected:
            logger.info("Closing database connections...")
            app.db.close()
            logger.info("Cleanup complete")

    def signal_handler(_sig: int, _frame: Any) -> None:
        """Handle interrupt signals gracefully."""
        logger.info("\nReceived interrupt signal, shutting down...")
        cleanup()
        logger.info("Goodbye!")
        import sys
        sys.exit(0)

    # Register cleanup handlers
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.debug("Cleanup handlers registered")


def _init_api_docs(app: LocalChatApp) -> None:
    """
    Initialize API documentation (Swagger/OpenAPI).

    Args:
        app: Flask application instance
    """
    try:
        from .api_docs import init_swagger

        swagger = init_swagger(app)
        app.swagger = swagger

        logger.info("API documentation initialized at /api/docs/")

    except ImportError as e:
        logger.warning(f"[!] API documentation not available: {e}")
    except Exception as e:
        logger.error(f"Error initializing API docs: {e}", exc_info=True)


def _init_monitoring(app: LocalChatApp) -> None:
    """
    Initialize monitoring and metrics.

    Args:
        app: Flask application instance
    """
    try:
        from .monitoring import init_monitoring

        init_monitoring(app)

        logger.info("Monitoring initialized at /api/metrics and /api/health")

    except Exception as e:
        logger.error(f"Error initializing monitoring: {e}", exc_info=True)


# Export for backward compatibility
__all__ = ['create_app']
