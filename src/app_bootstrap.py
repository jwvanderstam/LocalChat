"""Application bootstrap — all startup I/O for LocalChat.

Call bootstrap_app(app) after create_app() in production. Never call from tests.
Every function here performs network or filesystem I/O (Ollama, DB, Redis, plugins, connectors).
"""

import threading
from typing import Any

from . import config
from .utils.logging_config import get_logger, setup_logging

logger = get_logger(__name__)


def _run_alembic_migrations() -> None:
    """Apply any pending Alembic migrations after _init_schema() succeeds."""
    from pathlib import Path
    try:
        import alembic.command
        import alembic.config as alembic_config
    except ImportError:
        logger.warning("alembic not installed — skipping migration step")
        return

    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    if not ini_path.exists():
        logger.warning("alembic.ini not found at %s — skipping migration step", ini_path)
        return

    try:
        cfg = alembic_config.Config(str(ini_path))
        alembic.command.upgrade(cfg, "head")
        logger.info("Alembic migrations applied (or already at head)")
    except Exception as exc:
        logger.error("Alembic migration failed: %s", exc, exc_info=True)


def bootstrap_app(app: Any) -> None:
    """Start all services for a fully-wired LocalChat app.

    Assumes create_app() has already been called. Mutates app.state in-place:
    sets startup_status, embedding_cache, query_cache, sync_worker, etc.
    """
    log_level = "DEBUG" if config.APP_ENV != "production" else "INFO"
    setup_logging(log_level=log_level, log_file=config.LOG_FILE, log_format=config.LOG_FORMAT)

    _init_caching(app)

    db = app.state.db
    ollama_client = app.state.ollama_client
    doc_processor = app.state.doc_processor

    _init_ollama_service(app, ollama_client)
    _init_database_service(app, db)

    app.state.startup_status["ready"] = (
        app.state.startup_status["ollama"] and app.state.startup_status["database"]
    )

    if app.state.startup_status["database"]:
        _seed_admin_user(db)

    _load_plugins(app)
    _init_connectors(app, db, doc_processor)
    _init_reranker_scheduler(app, db)

    # Cleanup handlers registered last so sync_worker is already set
    _setup_cleanup_handlers(app)

    logger.info("Application bootstrap complete")


def _init_ollama_service(app: Any, ollama_client: Any) -> None:
    """Check Ollama availability and set the active model."""
    logger.info("Checking Ollama connection...")
    ollama_success, ollama_message = ollama_client.check_connection()
    app.state.startup_status["ollama"] = ollama_success
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


def _warmup_embedding_model(ollama_client: Any) -> None:
    """Trigger one embedding call at startup to pre-initialize CUDA kernels.

    Ollama lazily compiles GPU kernels on the first inference call, adding
    1–2 s of latency charged to the first user request. This amortises it.
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


def _init_database_service(app: Any, db: Any) -> None:
    """Initialise the database; abort if REQUIRE_DATABASE is set and DB is unavailable."""
    import sys

    logger.info("Checking PostgreSQL with pgvector...")
    db_success, db_message = db.initialize()
    app.state.startup_status["database"] = db_success
    if db_success:
        logger.info(db_message)
        _run_alembic_migrations()
        doc_count = db.get_document_count()
        config.app_state.set_document_count(doc_count)
        logger.info(f"Documents in database: {doc_count}")
        try:
            purged = db.purge_expired_tokens()
            if purged:
                logger.info("Purged %d expired revoked token(s)", purged)
        except Exception as _purge_err:
            logger.debug("Could not purge expired tokens: %s", _purge_err)
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


def _load_plugins(app: Any) -> None:
    """Scan the configured plugins directory and load all tool plugins."""
    if not config.PLUGINS_ENABLED:
        logger.info("[PLUGINS] Plugin loading disabled (PLUGINS_ENABLED=false)")
        return

    from pathlib import Path

    from .tools import plugin_loader

    plugins_dir = Path(config.PLUGINS_DIR)
    if not plugins_dir.is_absolute():
        plugins_dir = Path(__file__).parent.parent / plugins_dir

    count = plugin_loader.load_all(plugins_dir)
    if count:
        tool_names = [t for p in plugin_loader.list_plugins() for t in p["tools"]]
        logger.info(f"[PLUGINS] {count} plugin(s) loaded — tools: {tool_names}")
    app.state.plugin_loader = plugin_loader


def _init_reranker_scheduler(app: Any, db: Any) -> None:
    """Start a weekly background thread for reranker fine-tuning (opt-in)."""
    if not config.RERANKER_ENABLED:
        return
    try:
        import sentence_transformers  # noqa: F401 — check availability
    except ImportError:
        logger.info("[Reranker] sentence-transformers not installed — scheduler skipped")
        return

    _WEEK_SECONDS = 7 * 24 * 3600

    def _weekly_train() -> None:
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
                if not result.get("skipped"):
                    version_id = persist_reranker_version(db, result)
                    if version_id and result.get("ndcg_after", 0) > result.get("ndcg_before", 0):
                        promote_model(db, version_id)
                        logger.info("[Reranker] Weekly fine-tune complete — model promoted")
        except Exception as exc:
            logger.error(f"[Reranker] Weekly fine-tune failed: {exc}", exc_info=True)
        finally:
            t = threading.Timer(_WEEK_SECONDS, _weekly_train)
            t.daemon = True
            t.start()
            app.state._reranker_timer = t  # type: ignore[attr-defined]

    t = threading.Timer(_WEEK_SECONDS, _weekly_train)
    t.daemon = True
    t.start()
    app.state._reranker_timer = t  # type: ignore[attr-defined]
    logger.info("[Reranker] Weekly fine-tune scheduler started")


def _seed_admin_user(db: Any) -> None:
    """Idempotently seed the admin user if ADMIN_PASSWORD is configured.

    Uses an upsert so concurrent uvicorn workers are all safe to call this.
    """
    admin_password = config.ADMIN_PASSWORD
    if not admin_password:
        return
    try:
        from .db.users import hash_user_password
        db.seed_admin_user(
            username=config.ADMIN_USERNAME,
            hashed_password=hash_user_password(admin_password),
        )
    except Exception as exc:
        logger.warning(f"[Auth] Admin seeding skipped: {exc}")


def _init_connectors(app: Any, db: Any, doc_processor: Any) -> None:
    """Load connector instances from DB and start the background sync worker."""
    try:
        from .connectors.registry import connector_registry
        from .connectors.worker import SyncWorker
        connector_registry.load_from_db(db)
        worker = SyncWorker(connector_registry, db, doc_processor)
        worker.start()
        app.state.sync_worker = worker
        app.state.connector_registry = connector_registry
        logger.info("[Connectors] Sync worker started")
    except Exception as exc:
        logger.warning(f"[Connectors] Failed to start sync worker: {exc}", exc_info=True)
        app.state.sync_worker = None
        app.state.connector_registry = None


def _init_caching(app: Any) -> None:
    """Initialize caching layer (Redis or in-memory based on REDIS_ENABLED)."""
    try:
        from .cache import create_cache_backend
        from .cache.managers import init_caches

        if config.REDIS_ENABLED:
            cache_backend_type = "redis"
            backend_config: dict[str, Any] = {
                "host": config.REDIS_HOST,
                "port": config.REDIS_PORT,
                "password": config.REDIS_PASSWORD,
            }
        else:
            cache_backend_type = "memory"
            backend_config = {"max_size": 5000}

        embedding_backend = create_cache_backend(
            cache_backend_type, namespace="embeddings", **backend_config
        )

        query_backend_config = dict(backend_config)
        if cache_backend_type == "memory":
            query_backend_config["max_size"] = 1000

        query_backend = create_cache_backend(
            cache_backend_type, namespace="queries", **query_backend_config
        )

        embedding_cache, query_cache = init_caches(
            embedding_backend=embedding_backend,
            query_backend=query_backend,
            embedding_ttl=3600 * 24 * 7,
            query_ttl=3600,
        )

        app.state.embedding_cache = embedding_cache
        app.state.query_cache = query_cache

        logger.info(f"Caching initialized ({type(embedding_backend).__name__})")

    except Exception as e:
        if config.REDIS_ENABLED and config.REDIS_STRICT:
            import sys
            logger.critical(
                f"[!] Redis cache unavailable and REDIS_STRICT=true: {e}. "
                "Fix Redis connectivity or set REDIS_STRICT=false to allow memory fallback."
            )
            sys.exit(1)
        logger.warning(f"[!] Caching initialization failed: {e}")
        logger.warning("[!] Running without cache (will impact performance)")
        app.state.embedding_cache = None
        app.state.query_cache = None


def _setup_cleanup_handlers(app: Any) -> None:
    """Register atexit and signal handlers to shut down workers and close DB."""
    import atexit
    import signal

    def cleanup() -> None:
        sync_worker = getattr(app.state, "sync_worker", None)
        if sync_worker is not None:
            logger.info("Stopping connector sync worker...")
            sync_worker.stop()
        db = getattr(app.state, "db", None)
        if db is not None and db.is_connected:
            logger.info("Closing database connections...")
            db.close()
            logger.info("Cleanup complete")

    def signal_handler(_sig: int, _frame: Any) -> None:
        import sys
        logger.info("\nReceived interrupt signal, shutting down...")
        cleanup()
        logger.info("Goodbye!")
        sys.exit(0)

    atexit.register(cleanup)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    logger.debug("Cleanup handlers registered")


__all__ = ["bootstrap_app"]
