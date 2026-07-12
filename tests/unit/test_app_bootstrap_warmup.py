"""
App Bootstrap Warm-up Tests
===========================

Tests for the startup warm-up helpers and subsystem initializers in
src/app_bootstrap.py — every subsystem is I/O, mocked at its boundary here.
"""

import types
from unittest.mock import MagicMock, Mock, patch

import pytest

pytestmark = pytest.mark.unit


class TestWarmupReranker:
    """Test _warmup_reranker (src/app_bootstrap.py)."""

    def test_skips_when_reranker_disabled(self):
        from src.app_bootstrap import _warmup_reranker

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.RERANKER_ENABLED = False
            with patch("src.rag.reranker.get_reranker") as mock_get_reranker:
                _warmup_reranker()
                mock_get_reranker.assert_not_called()

    def test_loads_reranker_when_enabled(self):
        from src.app_bootstrap import _warmup_reranker

        mock_reranker = MagicMock()
        mock_reranker.is_available.return_value = True

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.RERANKER_ENABLED = True
            with patch("src.rag.reranker.get_reranker", return_value=mock_reranker) as mock_get_reranker:
                _warmup_reranker()
                mock_get_reranker.assert_called_once()

    def test_does_not_raise_when_reranker_load_fails(self):
        from src.app_bootstrap import _warmup_reranker

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.RERANKER_ENABLED = True
            with patch("src.rag.reranker.get_reranker", side_effect=RuntimeError("boom")):
                _warmup_reranker()  # must not raise — warm-up failures are non-fatal

    def test_logs_warning_when_no_reranker_model_available(self):
        from src.app_bootstrap import _warmup_reranker

        mock_reranker = MagicMock()
        mock_reranker.is_available.return_value = False

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.RERANKER_ENABLED = True
            with patch("src.rag.reranker.get_reranker", return_value=mock_reranker):
                _warmup_reranker()  # must not raise — logs a warning instead


class TestWarmupEmbeddingModel:
    """Test _warmup_embedding_model (src/app_bootstrap.py)."""

    def test_warms_up_embedding_model_successfully(self):
        from src.app_bootstrap import _warmup_embedding_model

        client = MagicMock()
        client.get_embedding_model.return_value = "nomic-embed-text"
        client.generate_embedding.return_value = (True, [0.1] * 8)

        _warmup_embedding_model(client)

        client.generate_embedding.assert_called_once_with("nomic-embed-text", "warmup")

    def test_skips_when_no_embedding_model_configured(self):
        from src.app_bootstrap import _warmup_embedding_model

        client = MagicMock()
        client.get_embedding_model.return_value = None

        _warmup_embedding_model(client)

        client.generate_embedding.assert_not_called()

    def test_does_not_raise_when_generate_embedding_returns_failure(self):
        from src.app_bootstrap import _warmup_embedding_model

        client = MagicMock()
        client.get_embedding_model.return_value = "nomic-embed-text"
        client.generate_embedding.return_value = (False, None)

        _warmup_embedding_model(client)  # non-fatal

    def test_does_not_raise_when_client_raises_exception(self):
        from src.app_bootstrap import _warmup_embedding_model

        client = MagicMock()
        client.get_embedding_model.side_effect = RuntimeError("boom")

        _warmup_embedding_model(client)  # non-fatal


class TestInitOllamaService:
    """Test _init_ollama_service (src/app_bootstrap.py)."""

    def test_sets_active_model_when_none_set_and_ollama_available(self):
        from src.app_bootstrap import _init_ollama_service

        app = MagicMock()
        app.state.startup_status = {}
        ollama_client = MagicMock()
        ollama_client.check_connection.return_value = (True, "Connected")
        ollama_client.get_first_available_model.return_value = "llama3.2"

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.DEFAULT_MODEL = "llama3.2"
            mock_config.app_state.get_active_model.return_value = None
            with patch("src.app_bootstrap._warmup_embedding_model") as mock_warmup_embed, \
                 patch("src.app_bootstrap._warmup_reranker") as mock_warmup_reranker:
                _init_ollama_service(app, ollama_client)

        assert app.state.startup_status["ollama"] is True
        mock_config.app_state.set_active_model.assert_called_once_with("llama3.2")
        mock_warmup_embed.assert_called_once_with(ollama_client)
        mock_warmup_reranker.assert_called_once()

    def test_does_not_overwrite_existing_active_model(self):
        from src.app_bootstrap import _init_ollama_service

        app = MagicMock()
        app.state.startup_status = {}
        ollama_client = MagicMock()
        ollama_client.check_connection.return_value = (True, "Connected")

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.app_state.get_active_model.return_value = "already-set"
            with patch("src.app_bootstrap._warmup_embedding_model"), \
                 patch("src.app_bootstrap._warmup_reranker"):
                _init_ollama_service(app, ollama_client)

        mock_config.app_state.set_active_model.assert_not_called()

    def test_skips_embedding_warmup_but_still_warms_reranker_when_ollama_unavailable(self):
        from src.app_bootstrap import _init_ollama_service

        app = MagicMock()
        app.state.startup_status = {}
        ollama_client = MagicMock()
        ollama_client.check_connection.return_value = (False, "connection refused")

        with patch("src.app_bootstrap.config"), \
             patch("src.app_bootstrap._warmup_embedding_model") as mock_warmup_embed, \
             patch("src.app_bootstrap._warmup_reranker") as mock_warmup_reranker:
            _init_ollama_service(app, ollama_client)

        assert app.state.startup_status["ollama"] is False
        mock_warmup_embed.assert_not_called()
        mock_warmup_reranker.assert_called_once()


class TestInitDatabaseService:
    """Test _init_database_service (src/app_bootstrap.py)."""

    def test_success_runs_migrations_and_purges_expired_tokens(self):
        from src.app_bootstrap import _init_database_service

        app = MagicMock()
        app.state.startup_status = {}
        db = MagicMock()
        db.initialize.return_value = (True, "Connected")
        db.get_document_count.return_value = 5
        db.purge_expired_tokens.return_value = 3

        with patch("src.app_bootstrap._run_alembic_migrations") as mock_migrate:
            _init_database_service(app, db)

        assert app.state.startup_status["database"] is True
        mock_migrate.assert_called_once()

    def test_continues_without_database_when_require_database_is_false(self):
        from src.app_bootstrap import _init_database_service

        app = MagicMock()
        app.state.startup_status = {}
        db = MagicMock()
        db.initialize.return_value = (False, "connection refused")

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.REQUIRE_DATABASE = False
            _init_database_service(app, db)

        assert app.state.startup_status["database"] is False

    def test_exits_when_database_unavailable_and_require_database_is_true(self):
        from src.app_bootstrap import _init_database_service

        app = MagicMock()
        app.state.startup_status = {}
        db = MagicMock()
        db.initialize.return_value = (False, "connection refused")

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.REQUIRE_DATABASE = True
            with pytest.raises(SystemExit):
                _init_database_service(app, db)

    def test_purge_expired_tokens_failure_is_non_fatal(self):
        from src.app_bootstrap import _init_database_service

        app = MagicMock()
        app.state.startup_status = {}
        db = MagicMock()
        db.initialize.return_value = (True, "Connected")
        db.get_document_count.return_value = 0
        db.purge_expired_tokens.side_effect = RuntimeError("boom")

        with patch("src.app_bootstrap._run_alembic_migrations"):
            _init_database_service(app, db)  # must not raise

        assert app.state.startup_status["database"] is True


class TestRunAlembicMigrations:
    """Test _run_alembic_migrations (src/app_bootstrap.py)."""

    def test_skips_when_alembic_not_installed(self):
        from src.app_bootstrap import _run_alembic_migrations

        with patch.dict("sys.modules", {"alembic.command": None, "alembic.config": None}):
            _run_alembic_migrations()  # must not raise

    def test_skips_when_alembic_ini_file_missing(self):
        from src.app_bootstrap import _run_alembic_migrations

        with patch("pathlib.Path.exists", return_value=False):
            _run_alembic_migrations()  # must not raise

    def test_applies_migrations_successfully(self):
        from src.app_bootstrap import _run_alembic_migrations

        mock_command = types.ModuleType("alembic.command")
        mock_command.upgrade = Mock()
        mock_config_mod = types.ModuleType("alembic.config")
        mock_config_mod.Config = Mock(return_value=Mock())
        mock_alembic_pkg = types.ModuleType("alembic")
        mock_alembic_pkg.command = mock_command
        mock_alembic_pkg.config = mock_config_mod

        with patch.dict("sys.modules", {
            "alembic": mock_alembic_pkg,
            "alembic.command": mock_command,
            "alembic.config": mock_config_mod,
        }):
            _run_alembic_migrations()

        mock_command.upgrade.assert_called_once()

    def test_logs_and_does_not_raise_when_migration_fails(self):
        from src.app_bootstrap import _run_alembic_migrations

        mock_command = types.ModuleType("alembic.command")
        mock_command.upgrade = Mock(side_effect=RuntimeError("boom"))
        mock_config_mod = types.ModuleType("alembic.config")
        mock_config_mod.Config = Mock(return_value=Mock())
        mock_alembic_pkg = types.ModuleType("alembic")
        mock_alembic_pkg.command = mock_command
        mock_alembic_pkg.config = mock_config_mod

        with patch.dict("sys.modules", {
            "alembic": mock_alembic_pkg,
            "alembic.command": mock_command,
            "alembic.config": mock_config_mod,
        }):
            _run_alembic_migrations()  # must not raise


class TestLoadPlugins:
    """Test _load_plugins (src/app_bootstrap.py)."""

    def test_skips_when_plugins_disabled(self):
        from src.app_bootstrap import _load_plugins
        from src.tools import plugin_loader as loader_singleton

        app = MagicMock()
        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.PLUGINS_ENABLED = False
            with patch.object(loader_singleton, "load_all") as mock_load_all:
                _load_plugins(app)

        mock_load_all.assert_not_called()

    def test_loads_plugins_and_logs_tool_names_when_enabled(self):
        from src.app_bootstrap import _load_plugins
        from src.tools import plugin_loader as loader_singleton

        app = MagicMock()
        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.PLUGINS_ENABLED = True
            mock_config.PLUGINS_DIR = "plugins"
            with patch.object(loader_singleton, "load_all", return_value=2) as mock_load_all, \
                 patch.object(loader_singleton, "list_plugins", return_value=[{"tools": ["echo"]}]):
                _load_plugins(app)

        mock_load_all.assert_called_once()
        assert app.state.plugin_loader is not None

    def test_skips_tool_name_lookup_when_zero_plugins_loaded(self):
        from src.app_bootstrap import _load_plugins
        from src.tools import plugin_loader as loader_singleton

        app = MagicMock()
        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.PLUGINS_ENABLED = True
            mock_config.PLUGINS_DIR = "plugins"
            with patch.object(loader_singleton, "load_all", return_value=0), \
                 patch.object(loader_singleton, "list_plugins") as mock_list:
                _load_plugins(app)

        mock_list.assert_not_called()


class TestInitRerankerScheduler:
    """Test _init_reranker_scheduler (src/app_bootstrap.py)."""

    def test_skips_when_reranker_disabled(self):
        from src.app_bootstrap import _init_reranker_scheduler

        app = MagicMock()
        db = MagicMock()
        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.RERANKER_ENABLED = False
            with patch("threading.Timer") as mock_timer:
                _init_reranker_scheduler(app, db)

        mock_timer.assert_not_called()

    def test_skips_when_sentence_transformers_not_installed(self):
        from src.app_bootstrap import _init_reranker_scheduler

        app = MagicMock()
        db = MagicMock()
        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.RERANKER_ENABLED = True
            with patch.dict("sys.modules", {"sentence_transformers": None}):
                with patch("threading.Timer") as mock_timer:
                    _init_reranker_scheduler(app, db)

        mock_timer.assert_not_called()

    def test_starts_weekly_timer_when_enabled_and_available(self):
        from src.app_bootstrap import _init_reranker_scheduler

        app = MagicMock()
        db = MagicMock()
        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.RERANKER_ENABLED = True
            with patch.dict("sys.modules", {"sentence_transformers": MagicMock()}):
                with patch("threading.Timer") as mock_timer_cls:
                    mock_timer_instance = MagicMock()
                    mock_timer_cls.return_value = mock_timer_instance
                    _init_reranker_scheduler(app, db)

        mock_timer_cls.assert_called_once()
        mock_timer_instance.start.assert_called_once()
        assert app.state._reranker_timer is mock_timer_instance


class TestWeeklyRerankerTrain:
    """Test the weekly fine-tune closure scheduled by _init_reranker_scheduler."""

    def _get_weekly_train(self, app, db):
        from src.app_bootstrap import _init_reranker_scheduler

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.RERANKER_ENABLED = True
            with patch.dict("sys.modules", {"sentence_transformers": MagicMock()}):
                with patch("threading.Timer") as mock_timer_cls:
                    mock_timer_cls.return_value = MagicMock()
                    _init_reranker_scheduler(app, db)

        return mock_timer_cls.call_args[0][1]

    def test_skips_finetune_when_below_minimum_pairs(self):
        app = MagicMock()
        db = MagicMock()
        weekly_train = self._get_weekly_train(app, db)

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.FEEDBACK_FINETUNE_MIN_PAIRS = 50
            with patch("src.rag.feedback_pipeline.export_training_pairs", return_value=[1, 2]) as mock_export, \
                 patch("src.rag.feedback_pipeline.finetune_reranker") as mock_finetune, \
                 patch("threading.Timer") as mock_timer_cls:
                mock_timer_cls.return_value = MagicMock()
                weekly_train()

        mock_export.assert_called_once_with(db, days=7)
        mock_finetune.assert_not_called()
        mock_timer_cls.assert_called_once()  # reschedules in finally

    def test_promotes_model_when_finetune_improves_ndcg(self):
        app = MagicMock()
        db = MagicMock()
        weekly_train = self._get_weekly_train(app, db)

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.FEEDBACK_FINETUNE_MIN_PAIRS = 1
            with patch("src.rag.feedback_pipeline.export_training_pairs", return_value=[1, 2, 3]), \
                 patch(
                     "src.rag.feedback_pipeline.finetune_reranker",
                     return_value={"skipped": False, "ndcg_before": 0.5, "ndcg_after": 0.8},
                 ), \
                 patch("src.rag.feedback_pipeline.persist_reranker_version", return_value="v2") as mock_persist, \
                 patch("src.rag.feedback_pipeline.promote_model") as mock_promote, \
                 patch("threading.Timer") as mock_timer_cls:
                mock_timer_cls.return_value = MagicMock()
                weekly_train()

        mock_persist.assert_called_once()
        mock_promote.assert_called_once_with(db, "v2")

    def test_does_not_promote_when_ndcg_does_not_improve(self):
        app = MagicMock()
        db = MagicMock()
        weekly_train = self._get_weekly_train(app, db)

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.FEEDBACK_FINETUNE_MIN_PAIRS = 1
            with patch("src.rag.feedback_pipeline.export_training_pairs", return_value=[1, 2, 3]), \
                 patch(
                     "src.rag.feedback_pipeline.finetune_reranker",
                     return_value={"skipped": False, "ndcg_before": 0.8, "ndcg_after": 0.5},
                 ), \
                 patch("src.rag.feedback_pipeline.persist_reranker_version", return_value="v2"), \
                 patch("src.rag.feedback_pipeline.promote_model") as mock_promote, \
                 patch("threading.Timer") as mock_timer_cls:
                mock_timer_cls.return_value = MagicMock()
                weekly_train()

        mock_promote.assert_not_called()

    def test_reschedules_after_exception(self):
        app = MagicMock()
        db = MagicMock()
        weekly_train = self._get_weekly_train(app, db)

        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.FEEDBACK_FINETUNE_MIN_PAIRS = 1
            with patch("src.rag.feedback_pipeline.export_training_pairs", side_effect=RuntimeError("boom")), \
                 patch("threading.Timer") as mock_timer_cls:
                mock_timer_cls.return_value = MagicMock()
                weekly_train()  # must not raise

        mock_timer_cls.assert_called_once()  # reschedules in finally despite the failure


class TestSeedAdminUser:
    """Test _seed_admin_user (src/app_bootstrap.py)."""

    def test_skips_when_no_admin_password_configured(self):
        from src.app_bootstrap import _seed_admin_user

        db = MagicMock()
        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.ADMIN_PASSWORD = ""
            _seed_admin_user(db)

        db.seed_admin_user.assert_not_called()

    def test_seeds_admin_user_when_password_configured(self):
        from src.app_bootstrap import _seed_admin_user

        db = MagicMock()
        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.ADMIN_PASSWORD = "s3cret"
            mock_config.ADMIN_USERNAME = "admin"
            with patch("src.db.users.hash_user_password", return_value="hashed") as mock_hash:
                _seed_admin_user(db)

        mock_hash.assert_called_once_with("s3cret")
        db.seed_admin_user.assert_called_once_with(username="admin", hashed_password="hashed")

    def test_does_not_raise_when_seeding_fails(self):
        from src.app_bootstrap import _seed_admin_user

        db = MagicMock()
        db.seed_admin_user.side_effect = RuntimeError("db down")
        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.ADMIN_PASSWORD = "s3cret"
            mock_config.ADMIN_USERNAME = "admin"
            with patch("src.db.users.hash_user_password", return_value="hashed"):
                _seed_admin_user(db)  # non-fatal


class TestInitConnectors:
    """Test _init_connectors (src/app_bootstrap.py)."""

    def test_starts_sync_worker_successfully(self):
        from src.app_bootstrap import _init_connectors

        app = MagicMock()
        db = MagicMock()
        doc_processor = MagicMock()
        with patch("src.connectors.registry.connector_registry") as mock_registry, \
             patch("src.connectors.worker.SyncWorker") as mock_worker_cls:
            mock_worker_instance = MagicMock()
            mock_worker_cls.return_value = mock_worker_instance
            _init_connectors(app, db, doc_processor)

        mock_registry.load_from_db.assert_called_once_with(db)
        mock_worker_instance.start.assert_called_once()
        assert app.state.sync_worker is mock_worker_instance
        assert app.state.connector_registry is mock_registry

    def test_sets_none_when_sync_worker_fails_to_start(self):
        from src.app_bootstrap import _init_connectors

        app = MagicMock()
        db = MagicMock()
        doc_processor = MagicMock()
        with patch("src.connectors.registry.connector_registry") as mock_registry:
            mock_registry.load_from_db.side_effect = RuntimeError("boom")
            _init_connectors(app, db, doc_processor)

        assert app.state.sync_worker is None
        assert app.state.connector_registry is None


class TestInitCaching:
    """Test _init_caching (src/app_bootstrap.py)."""

    def test_initializes_memory_backend_when_redis_disabled(self):
        from src.app_bootstrap import _init_caching

        app = MagicMock()
        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.REDIS_ENABLED = False
            with patch("src.cache.create_cache_backend") as mock_create_backend, \
                 patch("src.cache.managers.init_caches") as mock_init_caches:
                mock_create_backend.side_effect = [MagicMock(), MagicMock()]
                mock_init_caches.return_value = (MagicMock(), MagicMock())
                _init_caching(app)

        assert mock_create_backend.call_count == 2
        assert mock_create_backend.call_args_list[0].args[0] == "memory"
        assert app.state.embedding_cache is not None
        assert app.state.query_cache is not None

    def test_initializes_redis_backend_when_enabled(self):
        from src.app_bootstrap import _init_caching

        app = MagicMock()
        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.REDIS_ENABLED = True
            mock_config.REDIS_HOST = "localhost"
            mock_config.REDIS_PORT = 6379
            mock_config.REDIS_PASSWORD = None
            with patch("src.cache.create_cache_backend") as mock_create_backend, \
                 patch("src.cache.managers.init_caches") as mock_init_caches:
                mock_create_backend.side_effect = [MagicMock(), MagicMock()]
                mock_init_caches.return_value = (MagicMock(), MagicMock())
                _init_caching(app)

        assert mock_create_backend.call_args_list[0].args[0] == "redis"

    def test_falls_back_to_no_cache_when_init_fails_and_not_strict(self):
        from src.app_bootstrap import _init_caching

        app = MagicMock()
        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.REDIS_ENABLED = True
            mock_config.REDIS_STRICT = False
            with patch("src.cache.create_cache_backend", side_effect=RuntimeError("conn refused")):
                _init_caching(app)

        assert app.state.embedding_cache is None
        assert app.state.query_cache is None

    def test_exits_when_redis_unavailable_and_strict(self):
        from src.app_bootstrap import _init_caching

        app = MagicMock()
        with patch("src.app_bootstrap.config") as mock_config:
            mock_config.REDIS_ENABLED = True
            mock_config.REDIS_STRICT = True
            with patch("src.cache.create_cache_backend", side_effect=RuntimeError("conn refused")):
                with pytest.raises(SystemExit):
                    _init_caching(app)


class TestSetupCleanupHandlers:
    """Test _setup_cleanup_handlers (src/app_bootstrap.py)."""

    def test_cleanup_stops_sync_worker_and_closes_connected_db(self):
        from src.app_bootstrap import _setup_cleanup_handlers

        app = MagicMock()
        sync_worker = MagicMock()
        db = MagicMock()
        db.is_connected = True
        app.state.sync_worker = sync_worker
        app.state.db = db

        with patch("atexit.register") as mock_atexit, patch("signal.signal"):
            _setup_cleanup_handlers(app)

        cleanup_fn = mock_atexit.call_args[0][0]
        cleanup_fn()

        sync_worker.stop.assert_called_once()
        db.close.assert_called_once()

    def test_cleanup_skips_db_close_when_not_connected(self):
        from src.app_bootstrap import _setup_cleanup_handlers

        app = MagicMock()
        app.state.sync_worker = None
        db = MagicMock()
        db.is_connected = False
        app.state.db = db

        with patch("atexit.register") as mock_atexit, patch("signal.signal"):
            _setup_cleanup_handlers(app)

        cleanup_fn = mock_atexit.call_args[0][0]
        cleanup_fn()

        db.close.assert_not_called()

    def test_signal_handler_runs_cleanup_and_exits(self):
        from src.app_bootstrap import _setup_cleanup_handlers

        app = MagicMock()
        app.state.sync_worker = None
        app.state.db = None

        with patch("atexit.register"), patch("signal.signal") as mock_signal:
            _setup_cleanup_handlers(app)

        handler = mock_signal.call_args_list[0][0][1]
        with pytest.raises(SystemExit):
            handler(2, None)


class TestBootstrapApp:
    """Test bootstrap_app orchestration (src/app_bootstrap.py)."""

    def test_calls_all_subsystem_initializers_and_marks_ready(self):
        from src.app_bootstrap import bootstrap_app

        app = MagicMock()
        app.state.startup_status = {"ollama": False, "database": False, "ready": False}
        app.state.db = MagicMock()
        app.state.ollama_client = MagicMock()
        app.state.doc_processor = MagicMock()

        def _mark_ollama_ready(app_arg, *_a, **_kw):
            app_arg.state.startup_status["ollama"] = True

        def _mark_db_ready(app_arg, *_a, **_kw):
            app_arg.state.startup_status["database"] = True

        with patch("src.app_bootstrap.setup_logging") as mock_setup_logging, \
             patch("src.app_bootstrap._init_caching") as mock_init_caching, \
             patch("src.app_bootstrap._init_ollama_service", side_effect=_mark_ollama_ready) as mock_init_ollama, \
             patch("src.app_bootstrap._init_database_service", side_effect=_mark_db_ready) as mock_init_db, \
             patch("src.app_bootstrap._seed_admin_user") as mock_seed_admin, \
             patch("src.app_bootstrap._load_plugins") as mock_load_plugins, \
             patch("src.app_bootstrap._init_connectors") as mock_init_connectors, \
             patch("src.app_bootstrap._init_reranker_scheduler") as mock_init_reranker, \
             patch("src.app_bootstrap._setup_cleanup_handlers") as mock_setup_cleanup:
            bootstrap_app(app)

        mock_setup_logging.assert_called_once()
        mock_init_caching.assert_called_once_with(app)
        mock_init_ollama.assert_called_once()
        mock_init_db.assert_called_once()
        assert app.state.startup_status["ready"] is True
        mock_seed_admin.assert_called_once_with(app.state.db)
        mock_load_plugins.assert_called_once_with(app)
        mock_init_connectors.assert_called_once()
        mock_init_reranker.assert_called_once()
        mock_setup_cleanup.assert_called_once_with(app)

    def test_skips_seeding_admin_user_when_database_unavailable(self):
        from src.app_bootstrap import bootstrap_app

        app = MagicMock()
        app.state.startup_status = {"ollama": True, "database": False, "ready": False}
        app.state.db = MagicMock()
        app.state.ollama_client = MagicMock()
        app.state.doc_processor = MagicMock()

        with patch("src.app_bootstrap.setup_logging"), \
             patch("src.app_bootstrap._init_caching"), \
             patch("src.app_bootstrap._init_ollama_service"), \
             patch("src.app_bootstrap._init_database_service"), \
             patch("src.app_bootstrap._seed_admin_user") as mock_seed_admin, \
             patch("src.app_bootstrap._load_plugins"), \
             patch("src.app_bootstrap._init_connectors"), \
             patch("src.app_bootstrap._init_reranker_scheduler"), \
             patch("src.app_bootstrap._setup_cleanup_handlers"):
            bootstrap_app(app)

        assert app.state.startup_status["ready"] is False
        mock_seed_admin.assert_not_called()
