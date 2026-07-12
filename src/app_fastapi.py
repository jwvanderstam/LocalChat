"""FastAPI application factory — wiring only, no startup I/O.

Call create_app() to get a fully wired FastAPI app.  For production,
follow up with bootstrap_app(app) from src.app_bootstrap.

Tests call only create_app(), which is safe with zero mocking.
Pass config_override={'TESTING': True} to disable JWT and rate limiting.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from . import config
from .utils.logging_config import get_logger

logger = get_logger(__name__)


def create_app(config_override: dict[str, Any] | None = None) -> FastAPI:
    """Create and wire a FastAPI application instance (no I/O).

    Safe to call in tests without mocking.
    """
    config.validate_secrets()

    _cfg = config_override or {}
    testing = _cfg.get("TESTING", False)

    root_dir = Path(__file__).parent.parent
    upload_folder = _cfg.get("UPLOAD_FOLDER", config.UPLOAD_FOLDER)
    os.makedirs(upload_folder, exist_ok=True)

    app = FastAPI(
        title="LocalChat",
        version="1.0.0",
        docs_url="/api/docs/",
        openapi_url="/api/openapi.json",
    )

    # ── App state ──────────────────────────────────────────────────────────
    from .db import db
    from .ollama_client import ollama_client
    from .rag import doc_processor

    app.state.db = db
    app.state.ollama_client = ollama_client
    app.state.doc_processor = doc_processor
    app.state.cloud_client = _init_cloud_client()
    app.state.testing = testing
    app.state.upload_folder = upload_folder
    app.state.static_folder = str(root_dir / "static")
    app.state.template_folder = str(root_dir / "templates")

    # Placeholders overwritten by bootstrap
    app.state.sync_worker = None
    app.state.connector_registry = None
    app.state.embedding_cache = None
    app.state.query_cache = None
    app.state.plugin_loader = None
    app.state.startup_status = {"ollama": False, "database": False, "ready": False}

    # ── Security ───────────────────────────────────────────────────────────
    _init_security(app, testing)

    # ── Observability middlewares ───────────────────────────────────────────
    # Added after _init_security so they wrap _log_requests.
    # Last added = outermost: MetricsMiddleware → RequestIdMiddleware → _log_requests → routes
    _init_middlewares(app)

    # ── Routes ─────────────────────────────────────────────────────────────
    _register_routers(app)

    # ── Static files ───────────────────────────────────────────────────────
    static_dir = root_dir / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ── Error handlers ─────────────────────────────────────────────────────
    _register_error_handlers(app)

    logger.info("FastAPI application created (testing=%s)", testing)
    return app


def _init_middlewares(app: FastAPI) -> None:
    from .monitoring import MetricsMiddleware
    from .utils.request_id import RequestIdMiddleware

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(MetricsMiddleware)
    logger.info("Observability middlewares registered")


def _handle_rate_limit_exceeded(request: Request, exc: Exception) -> Response:
    """Adapt slowapi's narrowly-typed handler to Starlette's generic handler signature.

    ``add_exception_handler(RateLimitExceeded, ...)`` guarantees Starlette only ever
    dispatches ``RateLimitExceeded`` instances here.
    """
    from slowapi import _rate_limit_exceeded_handler
    assert isinstance(exc, RateLimitExceeded)
    return _rate_limit_exceeded_handler(request, exc)


def _init_security(app: FastAPI, testing: bool) -> None:
    from .security_fastapi import limiter, setup_cors

    setup_cors(app)

    if not testing:
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _handle_rate_limit_exceeded)

    @app.middleware("http")
    async def _log_requests(request: Request, call_next):
        from .utils.logging_config import sanitize_log_value as _slv
        logger.info("%s %s", _slv(request.method), _slv(request.url.path))
        response = await call_next(request)
        logger.debug("%s %s → %s", _slv(request.method), _slv(request.url.path), response.status_code)
        return response

    logger.info("Security middleware initialised")


def _init_cloud_client() -> Any:
    if not config.CLOUD_FALLBACK_ENABLED:
        return None
    if not config.CLOUD_MODEL:
        logger.warning("[CloudFallback] CLOUD_FALLBACK_ENABLED=true but CLOUD_MODEL is not set")
        return None
    try:
        from .llm_client import LiteLLMClient
        return LiteLLMClient(
            provider=config.CLOUD_PROVIDER,
            api_key=config.CLOUD_API_KEY,
            model=config.CLOUD_MODEL,
        )
    except ImportError as e:
        logger.warning(f"[CloudFallback] {e} — disabled")
        return None
    except Exception:
        logger.exception("[CloudFallback] Failed to initialise")
        return None


def _register_routers(app: FastAPI) -> None:
    from .routes_fastapi import (
        annotation_routes,
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

    app.include_router(web_routes.router)
    app.include_router(api_routes.router, prefix="/api")
    app.include_router(document_routes.router, prefix="/api/documents")
    app.include_router(model_routes.router, prefix="/api/models")
    app.include_router(memory_routes.router, prefix="/api")
    app.include_router(longterm_memory_routes.router, prefix="/api/memory")
    app.include_router(feedback_routes.router, prefix="/api")
    app.include_router(workspace_routes.router, prefix="/api")
    app.include_router(connector_routes.router, prefix="/api")
    app.include_router(settings_routes.router, prefix="/api")
    app.include_router(auth_routes.router, prefix="/api")
    app.include_router(oauth_routes.router, prefix="/api")
    app.include_router(annotation_routes.router, prefix="/api")

    logger.debug("Routers registered")


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(404)
    async def not_found(_request: Request, _exc):
        return JSONResponse({"success": False, "error": "NotFound", "message": "Resource not found"}, status_code=404)

    @app.exception_handler(405)
    async def method_not_allowed(_request: Request, _exc):
        return JSONResponse({"success": False, "error": "MethodNotAllowed", "message": "Method not allowed"}, status_code=405)

    @app.exception_handler(500)
    async def internal_error(_request: Request, _exc):
        logger.error("Unhandled exception", exc_info=_exc)
        return JSONResponse({"success": False, "error": "InternalServerError", "message": "An unexpected error occurred"}, status_code=500)


__all__ = ["create_app"]
