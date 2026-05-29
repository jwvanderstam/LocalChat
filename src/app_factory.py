"""Flask application factory — wiring only, no startup I/O.

Call create_app() to get a fully wired Flask app. For production, follow up with
bootstrap_app(app) from src.app_bootstrap to start services (Ollama, DB, connectors, etc.).

Tests call only create_app(), which is safe with zero mocking.
"""

import os
from pathlib import Path
from typing import Any

from . import config
from .types import LocalChatApp
from .utils.logging_config import get_logger

logger = get_logger(__name__)


def create_app(config_override: dict[str, Any] | None = None) -> LocalChatApp:
    """Create and wire a Flask application instance (no I/O).

    Safe to call in tests without mocking. Pass ``{'TESTING': True}`` via
    config_override to suppress JWT and rate-limit enforcement.

    For production use, call bootstrap_app(app) afterwards.
    """
    config.validate_secrets()

    root_dir = Path(__file__).parent.parent
    app = LocalChatApp(
        __name__,
        template_folder=str(root_dir / 'templates'),
        static_folder=str(root_dir / 'static')
    )

    _load_configuration(app, config_override)

    # Attach service singletons (import only — no network or DB I/O here)
    from .db import db
    from .ollama_client import ollama_client
    from .rag import doc_processor

    app.db = db
    app.ollama_client = ollama_client
    app.doc_processor = doc_processor
    app.cloud_client = _init_cloud_client()

    # Bootstrap will overwrite these; defaults keep code safe before bootstrap runs
    app.sync_worker = None
    app.connector_registry = None
    app.embedding_cache = None
    app.query_cache = None
    app.plugin_loader = None
    app.startup_status = {'ollama': False, 'database': False, 'ready': False}

    from .utils.request_id import init_request_id
    init_request_id(app)

    # Security must come before blueprints so the module-level limiter is bound
    # before @limiter.limit() decorators on blueprint routes are evaluated.
    _init_security(app)
    _register_blueprints(app)
    _register_error_handlers(app)

    logger.info("Flask application created")
    return app


def _load_configuration(
    app: LocalChatApp,
    config_override: dict[str, Any] | None,
) -> None:
    app.config['SECRET_KEY'] = config.SECRET_KEY
    app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
    app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER

    if config_override:
        app.config.update(config_override)

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    logger.debug("Configuration loaded")


def _init_security(app: LocalChatApp) -> None:
    # Skip JWT and rate limiting in testing mode. Flask-Limiter respects TESTING
    # for rate limits, but JWT still requires tokens — skip entirely so tests
    # don't need to supply auth headers on every request.
    if app.config.get('TESTING'):
        app.security_enabled = False
        return

    try:
        from . import security
        security.init_security(app)
        security.setup_auth_routes(app)
        security.setup_health_check(app)
        security.setup_rate_limit_handler(app)
        app.security_enabled = True
        logger.info("Security middleware initialized")
    except ImportError as e:
        app.security_enabled = False
        logger.warning(f"[!] Security middleware not available: {e}")


def _init_cloud_client() -> Any:
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


def _register_blueprints(app: LocalChatApp) -> None:
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
    from .routes import error_handlers
    error_handlers.register_error_handlers(app)
    logger.debug("Error handlers registered")


__all__ = ['create_app']
