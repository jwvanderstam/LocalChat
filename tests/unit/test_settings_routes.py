"""Unit tests for src/routes/settings_routes.py helper functions and endpoints."""

from unittest.mock import Mock, patch

import pytest

# ---------------------------------------------------------------------------
# _collect_document_stats
# ---------------------------------------------------------------------------

class TestCollectDocumentStats:
    """Tests for _collect_document_stats helper."""

    def test_returns_zeros_when_no_db(self):
        """Returns safe zeros when app has no db attribute."""
        from src.routes.settings_routes import _collect_document_stats

        app = Mock(spec=[])  # no attributes
        result = _collect_document_stats(app)

        assert result == {"document_count": 0, "chunk_count": 0, "db_available": False}

    def test_returns_zeros_when_db_is_none(self):
        """Returns safe zeros when app.db is None."""
        from src.routes.settings_routes import _collect_document_stats

        app = Mock()
        app.db = None
        result = _collect_document_stats(app)

        assert result["db_available"] is False
        assert result["document_count"] == 0

    def test_returns_counts_from_db(self):
        """Returns document and chunk counts from the database."""
        from src.routes.settings_routes import _collect_document_stats

        app = Mock()
        app.db = Mock()
        app.db.get_document_count.return_value = 5
        app.db.get_chunk_count.return_value = 42

        result = _collect_document_stats(app)

        assert result["document_count"] == 5
        assert result["chunk_count"] == 42
        assert result["db_available"] is True

    def test_returns_zeros_when_db_raises(self):
        """Returns safe zeros when the DB call raises an exception."""
        from src.routes.settings_routes import _collect_document_stats

        app = Mock()
        app.db = Mock()
        app.db.get_document_count.side_effect = Exception("DB error")

        result = _collect_document_stats(app)

        assert result["db_available"] is False
        assert result["document_count"] == 0


# ---------------------------------------------------------------------------
# _collect_cache_stats
# ---------------------------------------------------------------------------

class TestCollectCacheStats:
    """Tests for _collect_cache_stats helper."""

    def test_returns_unavailable_when_no_caches(self):
        """Both caches report unavailable when absent from app."""
        from src.routes.settings_routes import _collect_cache_stats

        app = Mock(spec=[])
        result = _collect_cache_stats(app)

        assert result["embedding_cache"]["available"] is False
        assert result["query_cache"]["available"] is False

    def test_returns_unavailable_when_cache_is_none(self):
        """Reports unavailable when cache attributes are explicitly None."""
        from src.routes.settings_routes import _collect_cache_stats

        app = Mock()
        app.embedding_cache = None
        app.query_cache = None

        result = _collect_cache_stats(app)

        assert result["embedding_cache"]["available"] is False
        assert result["query_cache"]["available"] is False

    def test_returns_stats_when_cache_available(self):
        """Returns hit_rate, usage_percent and counts when cache is present."""
        from src.routes.settings_routes import _collect_cache_stats

        mock_stats = Mock()
        mock_stats.hit_rate = 75.0
        mock_stats.usage_percent = 50.0
        mock_stats.hits = 30
        mock_stats.misses = 10
        mock_stats.size = 50
        mock_stats.max_size = 100

        app = Mock()
        app.embedding_cache = Mock()
        app.embedding_cache.get_stats.return_value = mock_stats
        app.query_cache = None

        result = _collect_cache_stats(app)

        ec = result["embedding_cache"]
        assert ec["available"] is True
        assert ec["hits"] == 30
        assert ec["misses"] == 10

    def test_returns_unavailable_when_cache_raises(self):
        """Handles exception from get_stats gracefully."""
        from src.routes.settings_routes import _collect_cache_stats

        app = Mock()
        app.embedding_cache = Mock()
        app.embedding_cache.get_stats.side_effect = RuntimeError("cache error")
        app.query_cache = None

        result = _collect_cache_stats(app)
        assert result["embedding_cache"]["available"] is False


# ---------------------------------------------------------------------------
# _collect_system_info
# ---------------------------------------------------------------------------

class TestCollectSystemInfo:
    """Tests for _collect_system_info helper."""

    def test_returns_required_keys(self):
        """Result always contains all expected keys including loaded_models and gpu_info."""
        from src.routes.settings_routes import _collect_system_info

        app = Mock(spec=[])
        result = _collect_system_info(app)

        assert "app_version" in result
        assert "active_model" in result
        assert "demo_mode" in result
        assert "ollama_available" in result
        assert "timestamp" in result
        assert "loaded_models" in result
        assert "gpu_info" in result

    def test_loaded_models_empty_when_no_ollama_client(self):
        """loaded_models is an empty list when ollama_client is absent."""
        from src.routes.settings_routes import _collect_system_info

        app = Mock(spec=[])
        result = _collect_system_info(app)
        assert result["loaded_models"] == []

    def test_loaded_models_populated_from_running_models(self):
        """loaded_models reflects GPU stats from ollama_client.get_running_models()."""
        from src.routes.settings_routes import _collect_system_info

        mock_client = Mock()
        mock_client.get_running_models.return_value = [
            {"name": "llama3:latest", "size": 4 * 1024 * 1024 * 1024,
             "size_vram": 4 * 1024 * 1024 * 1024, "processor": "100% GPU"},
        ]
        app = Mock()
        app.ollama_client = mock_client

        result = _collect_system_info(app)

        assert len(result["loaded_models"]) == 1
        m = result["loaded_models"][0]
        assert m["name"] == "llama3:latest"
        assert m["gpu_percent"] == 100
        assert m["processor"] == "100% GPU"
        assert m["vram_mb"] == m["size_mb"]

    def test_loaded_models_gpu_percent_partial(self):
        """gpu_percent is computed correctly for partial GPU offload."""
        from src.routes.settings_routes import _collect_system_info

        mock_client = Mock()
        mock_client.get_running_models.return_value = [
            {"name": "mistral:7b", "size": 8 * 1024 * 1024 * 1024,
             "size_vram": 4 * 1024 * 1024 * 1024, "processor": "50% GPU"},
        ]
        app = Mock()
        app.ollama_client = mock_client

        result = _collect_system_info(app)
        assert result["loaded_models"][0]["gpu_percent"] == 50

    def test_loaded_models_empty_on_zero_size(self):
        """gpu_percent is 0 when size is zero (avoids ZeroDivisionError)."""
        from src.routes.settings_routes import _collect_system_info

        mock_client = Mock()
        mock_client.get_running_models.return_value = [
            {"name": "tiny", "size": 0, "size_vram": 0, "processor": "CPU"},
        ]
        app = Mock()
        app.ollama_client = mock_client

        result = _collect_system_info(app)
        assert result["loaded_models"][0]["gpu_percent"] == 0

    def test_loaded_models_empty_on_get_running_models_exception(self):
        """loaded_models is [] when get_running_models raises."""
        from src.routes.settings_routes import _collect_system_info

        mock_client = Mock()
        mock_client.get_running_models.side_effect = RuntimeError("ps error")
        app = Mock()
        app.ollama_client = mock_client

        result = _collect_system_info(app)
        assert result["loaded_models"] == []

    def test_active_model_fallback_on_error(self):
        """Falls back to '—' when get_active_model raises."""
        from src.routes.settings_routes import _collect_system_info

        app = Mock(spec=[])
        with patch("src.routes.settings_routes.config") as mock_cfg:
            mock_cfg.app_state.get_active_model.side_effect = Exception("fail")
            mock_cfg.APP_VERSION = "1.0"
            mock_cfg.DEMO_MODE = False

            result = _collect_system_info(app)

        assert result["active_model"] == "—"

    def test_reads_active_model_from_app_state(self):
        """Returns model name from config.app_state."""
        from src.routes.settings_routes import _collect_system_info

        app = Mock(spec=[])
        with patch("src.routes.settings_routes.config") as mock_cfg:
            mock_cfg.app_state.get_active_model.return_value = "llama3"
            mock_cfg.APP_VERSION = "2.0"
            mock_cfg.DEMO_MODE = True

            result = _collect_system_info(app)

        assert result["active_model"] == "llama3"

    def test_ollama_available_from_startup_status(self):
        """Reads ollama_available from app.startup_status."""
        from src.routes.settings_routes import _collect_system_info

        app = Mock()
        app.startup_status = {"ollama": True}

        result = _collect_system_info(app)
        assert result["ollama_available"] is True

    def test_gpu_info_empty_when_no_ollama_client(self):
        """gpu_info is [] when ollama_client is absent."""
        from src.routes.settings_routes import _collect_system_info

        app = Mock(spec=[])
        result = _collect_system_info(app)
        assert result["gpu_info"] == []

    def test_gpu_info_populated_from_get_gpu_info(self):
        """gpu_info reflects data from ollama_client.get_gpu_info()."""
        from src.routes.settings_routes import _collect_system_info

        mock_client = Mock()
        mock_client.get_running_models.return_value = []
        mock_client.get_gpu_info.return_value = [
            {
                "id": 0, "name": "RTX 5070", "vendor": "NVIDIA",
                "vram_total_mb": 12288, "vram_used_mb": 595,
                "vram_free_mb": 11693, "utilization_percent": 42,
                "temperature_c": 65,
            }
        ]
        app = Mock()
        app.ollama_client = mock_client

        result = _collect_system_info(app)
        assert len(result["gpu_info"]) == 1
        g = result["gpu_info"][0]
        assert g["vendor"] == "NVIDIA"
        assert g["vram_total_mb"] == 12288
        assert g["temperature_c"] == 65

    def test_gpu_info_empty_on_get_gpu_info_exception(self):
        """gpu_info is [] when get_gpu_info raises."""
        from src.routes.settings_routes import _collect_system_info

        mock_client = Mock()
        mock_client.get_running_models.return_value = []
        mock_client.get_gpu_info.side_effect = RuntimeError("smi error")
        app = Mock()
        app.ollama_client = mock_client

        result = _collect_system_info(app)
        assert result["gpu_info"] == []


# ---------------------------------------------------------------------------
# GPU detection helpers (OllamaClient)
# ---------------------------------------------------------------------------

class TestGetGpuInfo:
    """Tests for OllamaClient.get_gpu_info / _get_nvidia_gpu_info / _get_amd_gpu_info."""

    def _make_client(self):
        from src.ollama_client import OllamaClient
        return OllamaClient(base_url="http://localhost:11434")

    def test_returns_nvidia_when_available(self):
        """get_gpu_info returns NVIDIA results when nvidia-smi is found."""
        client = self._make_client()
        nvidia_output = "0, NVIDIA RTX 5070, 12288, 595, 11693, 42, 65\n"
        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0, stdout=nvidia_output)
                gpus = client.get_gpu_info()

        assert len(gpus) == 1
        assert gpus[0]["vendor"] == "NVIDIA"
        assert gpus[0]["vram_total_mb"] == 12288
        assert gpus[0]["utilization_percent"] == 42
        assert gpus[0]["temperature_c"] == 65

    def test_returns_multiple_nvidia_gpus(self):
        """Correctly parses multiple NVIDIA GPU lines."""
        client = self._make_client()
        nvidia_output = (
            "0, NVIDIA RTX 5070, 12288, 595, 11693, 42, 65\n"
            "1, NVIDIA RTX 3080, 10240, 0, 10240, 0, 45\n"
        )
        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0, stdout=nvidia_output)
                gpus = client.get_gpu_info()

        assert len(gpus) == 2
        assert gpus[0]["id"] == 0
        assert gpus[1]["id"] == 1
        assert gpus[1]["name"] == "NVIDIA RTX 3080"

    def test_falls_back_to_amd_when_nvidia_absent(self):
        """Falls back to AMD when nvidia-smi is not found."""
        import json as _json
        client = self._make_client()
        amd_output = _json.dumps({
            "card0": {
                "Card Series": "AMD RX 7900 XTX",
                "VRAM Total Memory (B)": str(24 * 1024 * 1024 * 1024),
                "VRAM Total Used Memory (B)": str(2 * 1024 * 1024 * 1024),
                "GPU use (%)": "55",
            }
        })

        def _which(cmd):
            return None if cmd == "nvidia-smi" else "/usr/bin/rocm-smi"

        with patch("shutil.which", side_effect=_which):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0, stdout=amd_output)
                gpus = client.get_gpu_info()

        assert len(gpus) == 1
        assert gpus[0]["vendor"] == "AMD"
        assert gpus[0]["vram_total_mb"] == 24 * 1024
        assert gpus[0]["utilization_percent"] == 55

    def test_returns_empty_when_no_tools_found(self):
        """Returns [] when neither nvidia-smi nor rocm-smi is available."""
        client = self._make_client()
        with patch("shutil.which", return_value=None):
            gpus = client.get_gpu_info()
        assert gpus == []

    def test_nvidia_returns_empty_on_nonzero_exit(self):
        """_get_nvidia_gpu_info returns [] when nvidia-smi exits non-zero."""
        client = self._make_client()
        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=1, stdout="")
                gpus = client._gpu_monitor._get_nvidia_gpu_info()
        assert gpus == []

    def test_amd_returns_empty_on_nonzero_exit(self):
        """_get_amd_gpu_info returns [] when rocm-smi exits non-zero."""
        client = self._make_client()
        with patch("shutil.which", return_value="/usr/bin/rocm-smi"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=1, stdout="")
                gpus = client._gpu_monitor._get_amd_gpu_info()
        assert gpus == []

    def test_nvidia_returns_empty_on_exception(self):
        """_get_nvidia_gpu_info returns [] when subprocess raises."""
        client = self._make_client()
        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"):
            with patch("subprocess.run", side_effect=OSError("not found")):
                gpus = client._gpu_monitor._get_nvidia_gpu_info()
        assert gpus == []

    def test_amd_handles_invalid_json(self):
        """_get_amd_gpu_info returns [] when rocm-smi output is invalid JSON."""
        client = self._make_client()
        with patch("shutil.which", return_value="/usr/bin/rocm-smi"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0, stdout="not json")
                gpus = client._gpu_monitor._get_amd_gpu_info()
        assert gpus == []

    # -- TTL cache tests -------------------------------------------------------

    def test_gpu_info_cache_hit_skips_subprocess(self):
        """get_gpu_info returns cached data and does not call subprocess again."""
        client = self._make_client()
        nvidia_output = "0, NVIDIA RTX 5070, 12288, 595, 11693, 42, 65\n"

        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0, stdout=nvidia_output)
                first = client.get_gpu_info()
                second = client.get_gpu_info()   # should hit cache

        assert first == second
        assert mock_run.call_count == 1          # subprocess called exactly once

    def test_gpu_info_cache_expires(self):
        """get_gpu_info re-queries when TTL has elapsed."""
        client = self._make_client()
        client._gpu_monitor._ttl = 0.0          # force immediate expiry
        nvidia_output = "0, NVIDIA RTX 5070, 12288, 595, 11693, 42, 65\n"

        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0, stdout=nvidia_output)
                client.get_gpu_info()
                client.get_gpu_info()           # TTL=0 → always expired

        assert mock_run.call_count == 2

    def test_running_models_cache_hit_skips_http(self):
        """get_running_models returns cached data and does not make a second HTTP call."""
        client = self._make_client()
        models_payload = {"models": [{"name": "llama3:latest"}]}

        with patch.object(client._session, "get") as mock_get:
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = models_payload
            mock_get.return_value = mock_resp

            first = client.get_running_models()
            second = client.get_running_models()   # cache hit

        assert first == second
        assert mock_get.call_count == 1

    def test_running_models_returns_stale_cache_on_error(self):
        """Stale cached data is returned when the /api/ps request fails."""
        client = self._make_client()
        client._running_models_cache = [{"name": "cached_model"}]
        client._running_models_cache_time = 0.0   # expired
        client._RUNNING_MODELS_TTL = 999.0        # won't expire again

        with patch.object(client._session, "get", side_effect=OSError("offline")):
            result = client.get_running_models()

        assert result == [{"name": "cached_model"}]


# ---------------------------------------------------------------------------
# gather_admin_stats
# ---------------------------------------------------------------------------

class TestGatherAdminStats:
    """Tests for gather_admin_stats aggregator."""

    def test_returns_all_top_level_keys(self):
        """Result contains documents, cache, health, system, metrics."""
        from src.routes.settings_routes import gather_admin_stats

        app = Mock(spec=[])
        result = gather_admin_stats(app)

        assert "documents" in result
        assert "cache" in result
        assert "health" in result
        assert "system" in result
        assert "metrics" in result

    def test_metrics_contains_uptime_and_request_count(self):
        """metrics sub-dict has uptime_seconds and request_count."""
        from src.monitoring import get_metrics
        from src.routes.settings_routes import gather_admin_stats

        get_metrics().reset()
        get_metrics().increment("http_requests_total", labels={"method": "GET"})

        app = Mock(spec=[])
        result = gather_admin_stats(app)

        assert "uptime_seconds" in result["metrics"]
        assert result["metrics"]["request_count"] >= 1


# ---------------------------------------------------------------------------
# Route endpoints
# ---------------------------------------------------------------------------

class TestSettingsRouteEndpoints:
    """Test /settings and /api/settings/stats via the test client."""

    def test_settings_stats_api_returns_200(self, client):
        """/api/settings/stats returns 200 and valid JSON."""
        response = client.get("/api/settings/stats")
        assert response.status_code == 200
        data = response.get_json()
        assert "documents" in data
        assert "cache" in data
        assert "health" in data
        assert "system" in data
        assert "metrics" in data

    def test_settings_dashboard_returns_html(self, client):
        """/settings renders an HTML page."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert b"html" in response.data.lower()

    def test_settings_stats_includes_rag_key(self, client):
        """/api/settings/stats response includes a 'rag' sub-dict."""
        response = client.get("/api/settings/stats")
        assert response.status_code == 200
        data = response.get_json()
        assert "rag" in data
        rag = data["rag"]
        assert "TOP_K_RESULTS" in rag
        assert "RERANK_TOP_K" in rag
        assert "DIVERSITY_THRESHOLD" in rag
        assert "SEMANTIC_WEIGHT" in rag
        assert "CHUNK_SIZE" in rag
        assert "CHUNK_OVERLAP" in rag


# ---------------------------------------------------------------------------
# RAG parameter endpoints
# ---------------------------------------------------------------------------

class TestRagParamsEndpoints:
    """Tests for GET/POST /api/settings/rag."""

    @pytest.fixture(autouse=True)
    def _restore_config(self):
        """Restore config RAG params after each test so mutations don't bleed."""
        from src import config
        saved = {
            "TOP_K_RESULTS":       config.TOP_K_RESULTS,
            "RERANK_TOP_K":        config.RERANK_TOP_K,
            "DIVERSITY_THRESHOLD": config.DIVERSITY_THRESHOLD,
            "SEMANTIC_WEIGHT":     config.SEMANTIC_WEIGHT,
        }
        yield
        for k, v in saved.items():
            setattr(config, k, v)

    def test_get_returns_current_values_and_ranges(self, client):
        """GET /api/settings/rag returns success, params with value/min/max."""
        response = client.get("/api/settings/rag")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        for key in ("TOP_K_RESULTS", "RERANK_TOP_K", "DIVERSITY_THRESHOLD", "SEMANTIC_WEIGHT"):
            assert key in data["params"]
            p = data["params"][key]
            assert "value" in p
            assert "min" in p
            assert "max" in p
            assert p["min"] <= p["value"] <= p["max"]

    def test_post_valid_params_updates_config(self, client):
        """POST with valid values returns success and 'updated' dict."""
        response = client.post(
            "/api/settings/rag",
            json={"TOP_K_RESULTS": 25, "RERANK_TOP_K": 10},
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["updated"]["TOP_K_RESULTS"] == 25
        assert data["updated"]["RERANK_TOP_K"] == 10

    def test_post_float_params_updates_config(self, client):
        """POST accepts float params like DIVERSITY_THRESHOLD."""
        response = client.post(
            "/api/settings/rag",
            json={"DIVERSITY_THRESHOLD": 0.80},
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert abs(data["updated"]["DIVERSITY_THRESHOLD"] - 0.80) < 1e-9

    def test_post_rejects_out_of_range_value(self, client):
        """POST with TOP_K_RESULTS > 50 returns 400 with error message."""
        response = client.post(
            "/api/settings/rag",
            json={"TOP_K_RESULTS": 999},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False
        assert any("TOP_K_RESULTS" in e for e in data["errors"])

    def test_post_rejects_rerank_exceeds_top_k(self, client):
        """POST where RERANK_TOP_K > TOP_K_RESULTS returns 400."""
        response = client.post(
            "/api/settings/rag",
            json={"TOP_K_RESULTS": 10, "RERANK_TOP_K": 15},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False
        assert any("RERANK_TOP_K" in e for e in data["errors"])

    def test_post_rejects_unknown_key(self, client):
        """POST with an unknown parameter key returns 400."""
        response = client.post(
            "/api/settings/rag",
            json={"UNKNOWN_PARAM": 42},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False

    def test_post_empty_body_succeeds_with_no_updates(self, client):
        """POST with an empty body succeeds (nothing to update)."""
        response = client.post(
            "/api/settings/rag",
            json={},
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["updated"] == {}

    def test_post_persists_change_visible_in_get(self, client):
        """A POST update is immediately visible in subsequent GET."""
        client.post(
            "/api/settings/rag",
            json={"TOP_K_RESULTS": 40},
            content_type="application/json",
        )
        get_resp = client.get("/api/settings/rag")
        data = get_resp.get_json()
        assert data["params"]["TOP_K_RESULTS"]["value"] == 40
