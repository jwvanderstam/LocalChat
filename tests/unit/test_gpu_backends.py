"""Unit tests for src/gpu/backends.py (MM-1)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_subprocess_result(stdout: str, returncode: int = 0) -> MagicMock:
    r = MagicMock()
    r.stdout = stdout
    r.returncode = returncode
    return r


# ---------------------------------------------------------------------------
# NvidiaBackend
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestNvidiaBackend:
    def test_probe_returns_none_when_nvidia_smi_absent(self):
        from src.gpu.backends import NvidiaBackend

        with patch("shutil.which", return_value=None):
            assert NvidiaBackend.probe() is None

    def test_probe_parses_single_gpu(self):
        from src.gpu.backends import NvidiaBackend

        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"):
            with patch("subprocess.run", return_value=_make_subprocess_result("8192, 6000\n")):
                b = NvidiaBackend.probe()

        assert b is not None
        assert b.total_mb == 8192
        assert b.free_mb == 6000
        assert b.backend_name == "NVIDIA"
        assert b.memory_model == "dedicated"

    def test_probe_sums_multiple_gpus(self):
        from src.gpu.backends import NvidiaBackend

        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"):
            with patch(
                "subprocess.run",
                return_value=_make_subprocess_result("8192, 6000\n8192, 5500\n"),
            ):
                b = NvidiaBackend.probe()

        assert b is not None
        assert b.total_mb == 16384
        assert b.free_mb == 11500

    def test_probe_returns_none_on_nonzero_returncode(self):
        from src.gpu.backends import NvidiaBackend

        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"):
            with patch("subprocess.run", return_value=_make_subprocess_result("", returncode=1)):
                assert NvidiaBackend.probe() is None

    def test_probe_returns_none_on_exception(self):
        from src.gpu.backends import NvidiaBackend

        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"):
            with patch("subprocess.run", side_effect=OSError("timeout")):
                assert NvidiaBackend.probe() is None


# ---------------------------------------------------------------------------
# AmdBackend (stub)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAmdBackend:
    def test_probe_returns_none(self):
        from src.gpu.backends import AmdBackend

        assert AmdBackend.probe() is None


# ---------------------------------------------------------------------------
# AppleBackend
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAppleBackend:
    def test_probe_returns_none_on_non_darwin(self):
        from src.gpu.backends import AppleBackend

        with patch("platform.system", return_value="Linux"):
            assert AppleBackend.probe() is None

    def test_probe_parses_sysctl_output(self):
        from src.gpu.backends import AppleBackend

        sysctl_out = "hw.memsize: 17179869184\n"  # 16 GB
        with patch("platform.system", return_value="Darwin"):
            with patch("subprocess.run", return_value=_make_subprocess_result(sysctl_out)):
                b = AppleBackend.probe()

        assert b is not None
        assert b.total_mb == 16384
        assert b.free_mb == 16384  # unified memory: free == total
        assert b.backend_name == "Apple"
        assert b.memory_model == "shared"

    def test_probe_returns_none_on_sysctl_failure(self):
        from src.gpu.backends import AppleBackend

        with patch("platform.system", return_value="Darwin"):
            with patch("subprocess.run", return_value=_make_subprocess_result("", returncode=1)):
                assert AppleBackend.probe() is None


# ---------------------------------------------------------------------------
# CpuBackend
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCpuBackend:
    def test_probe_uses_psutil(self):
        import sys
        import types

        from src.gpu.backends import CpuBackend

        mock_psutil = types.ModuleType("psutil")
        mock_mem = MagicMock()
        mock_mem.total = 16 * 1024 ** 3  # 16 GB
        mock_mem.available = 8 * 1024 ** 3  # 8 GB
        mock_psutil.virtual_memory = MagicMock(return_value=mock_mem)

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            b = CpuBackend.probe()

        assert b.total_mb == 16384
        assert b.free_mb == 8192
        assert b.backend_name == "CPU"
        assert b.memory_model == "shared"

    def test_probe_returns_zeros_when_psutil_missing(self):
        import builtins

        from src.gpu.backends import CpuBackend

        real_import = builtins.__import__

        def mock_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "psutil":
                raise ImportError("no module")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            b = CpuBackend.probe()

        assert b.total_mb == 0
        assert b.free_mb == 0


# ---------------------------------------------------------------------------
# detect() factory
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDetect:
    def test_auto_returns_nvidia_when_available(self):
        from src.gpu.backends import NvidiaBackend, detect

        nvidia = NvidiaBackend(8192, 6000)
        with patch("src.gpu.backends.NvidiaBackend.probe", return_value=nvidia):
            b = detect("auto")

        assert b is nvidia

    def test_auto_falls_through_to_cpu_when_no_gpu(self):
        from src.gpu.backends import CpuBackend, detect

        cpu = CpuBackend(16384, 8192)
        with patch("src.gpu.backends.NvidiaBackend.probe", return_value=None):
            with patch("src.gpu.backends.AmdBackend.probe", return_value=None):
                with patch("src.gpu.backends.AppleBackend.probe", return_value=None):
                    with patch("src.gpu.backends.CpuBackend.probe", return_value=cpu):
                        b = detect("auto")

        assert b is cpu

    def test_force_nvidia_falls_back_to_cpu(self):
        from src.gpu.backends import CpuBackend, detect

        cpu = CpuBackend(16384, 8192)
        with patch("src.gpu.backends.NvidiaBackend.probe", return_value=None):
            with patch("src.gpu.backends.CpuBackend.probe", return_value=cpu):
                b = detect("nvidia")

        assert b is cpu

    def test_force_apple_returns_apple_when_available(self):
        from src.gpu.backends import AppleBackend, detect

        apple = AppleBackend(16384, 16384)
        with patch("src.gpu.backends.AppleBackend.probe", return_value=apple):
            b = detect("apple")

        assert b is apple

    def test_force_apple_falls_back_to_cpu(self):
        from src.gpu.backends import CpuBackend, detect

        cpu = CpuBackend(16384, 8192)
        with patch("src.gpu.backends.AppleBackend.probe", return_value=None):
            with patch("src.gpu.backends.CpuBackend.probe", return_value=cpu):
                b = detect("apple")

        assert b is cpu

    def test_force_cpu_skips_probes(self):
        from src.gpu.backends import CpuBackend, detect

        cpu = CpuBackend(16384, 8192)
        with patch("src.gpu.backends.CpuBackend.probe", return_value=cpu):
            with patch("src.gpu.backends.NvidiaBackend.probe") as mock_nvidia:
                b = detect("cpu")

        assert b is cpu
        mock_nvidia.assert_not_called()


# ---------------------------------------------------------------------------
# Budget calculation semantics
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBudgetSemantics:
    def test_dedicated_budget_is_free_mb(self):
        from src.gpu.backends import NvidiaBackend

        b = NvidiaBackend(total_mb=8192, free_mb=5000)
        assert b.free_mb == 5000
        assert b.memory_model == "dedicated"

    def test_shared_budget_uses_os_reserve(self):
        """Shared backends expose total_mb; caller subtracts OS reserve."""
        from src.gpu.backends import CpuBackend

        b = CpuBackend(total_mb=16384, free_mb=8192)
        os_reserve = 3000
        budget = b.total_mb - os_reserve
        assert budget == 13384
        assert b.memory_model == "shared"


# ---------------------------------------------------------------------------
# OllamaClient.estimate_model_footprint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEstimateModelFootprint:
    def _make_client(self) -> object:
        from unittest.mock import MagicMock

        from src.ollama_client import OllamaClient

        client = OllamaClient.__new__(OllamaClient)
        client._list_models_cache = None
        client._list_models_cache_time = 0.0
        client._gpu_monitor = MagicMock()
        return client

    def test_returns_size_plus_headroom(self):
        from src.ollama_client import OllamaClient

        client = OllamaClient.__new__(OllamaClient)
        # 7 GB model on disk
        size_bytes = 7 * 1024 ** 3
        models = [{"name": "llama3.1:8b", "size": size_bytes, "modified_at": "", "digest": ""}]
        with patch.object(OllamaClient, "list_models", return_value=(True, models)):
            footprint = client.estimate_model_footprint("llama3.1:8b")

        from src import config

        assert footprint == size_bytes // (1024 * 1024) + config.MODEL_VRAM_HEADROOM_MB

    def test_returns_headroom_only_for_unknown_model(self):
        from src import config
        from src.ollama_client import OllamaClient

        client = OllamaClient.__new__(OllamaClient)
        with patch.object(OllamaClient, "list_models", return_value=(True, [])):
            footprint = client.estimate_model_footprint("unknown-model")

        assert footprint == config.MODEL_VRAM_HEADROOM_MB


# ---------------------------------------------------------------------------
# OllamaClient.load_model_guard
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLoadModelGuard:
    def _make_client(self):
        from src.ollama_client import OllamaClient

        return OllamaClient.__new__(OllamaClient)

    def _make_backend(self, *, memory_model: str, total_mb: int, free_mb: int, name: str = "NVIDIA"):
        b = MagicMock()
        b.memory_model = memory_model
        b.total_mb = total_mb
        b.free_mb = free_mb
        b.backend_name = name
        return b

    def test_raises_when_dedicated_oversized_and_flag_false(self):
        from src import config
        from src.ollama_client import OllamaClient

        client = self._make_client()
        backend = self._make_backend(memory_model="dedicated", total_mb=8192, free_mb=2000)

        # footprint = 5000 MB (fits check: 5000 > 2000 → too big)
        with patch.object(OllamaClient, "estimate_model_footprint", return_value=5000):
            with patch.object(config, "MODEL_ALLOW_OVERSIZED", False):
                with pytest.raises(ValueError, match="5,000 MB"):
                    client.load_model_guard("bigmodel", backend)

    def test_warns_but_does_not_raise_when_flag_true(self):
        import logging

        from src import config
        from src.ollama_client import OllamaClient

        client = self._make_client()
        backend = self._make_backend(memory_model="dedicated", total_mb=8192, free_mb=2000)

        with patch.object(OllamaClient, "estimate_model_footprint", return_value=5000):
            with patch.object(config, "MODEL_ALLOW_OVERSIZED", True):
                with patch("src.ollama_client.logger") as mock_log:
                    client.load_model_guard("bigmodel", backend)
                    mock_log.warning.assert_called_once()

    def test_passes_silently_when_model_fits(self):
        from src import config
        from src.ollama_client import OllamaClient

        client = self._make_client()
        backend = self._make_backend(memory_model="dedicated", total_mb=8192, free_mb=8000)

        with patch.object(OllamaClient, "estimate_model_footprint", return_value=3000):
            with patch.object(config, "MODEL_ALLOW_OVERSIZED", False):
                client.load_model_guard("smallmodel", backend)  # must not raise

    def test_shared_backend_uses_os_reserve(self):
        from src import config
        from src.ollama_client import OllamaClient

        client = self._make_client()
        # 16 GB RAM, OS reserve 3 GB → budget 13 GB
        backend = self._make_backend(
            memory_model="shared", total_mb=16384, free_mb=8192, name="CPU"
        )

        with patch.object(OllamaClient, "estimate_model_footprint", return_value=14000):
            with patch.object(config, "MODEL_ALLOW_OVERSIZED", False):
                with patch.object(config, "SHARED_POOL_OS_RESERVE_MB", 3000):
                    with pytest.raises(ValueError, match="13,384 MB"):
                        client.load_model_guard("hugemodel", backend)


# ---------------------------------------------------------------------------
# model_routes list_models enrichment
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestListModelsEnrichment:
    def _make_app_and_client(self, models):
        from unittest.mock import MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.routes_fastapi.model_routes import router

        app = FastAPI()
        app.include_router(router, prefix="/api/models")
        app.state = MagicMock()
        app.state.ollama_client.list_models.return_value = (True, models)
        return app, TestClient(app, raise_server_exceptions=True)

    def test_enriched_fields_present(self):
        models = [{"name": "llama3.1:8b", "size": 4 * 1024 ** 3, "modified_at": "", "digest": ""}]
        app, client = self._make_app_and_client(models)

        from src.gpu.backends import CpuBackend

        cpu = CpuBackend(total_mb=32768, free_mb=16384)
        with patch("src.gpu.backends.detect", return_value=cpu):
            app.state.ollama_client.estimate_model_footprint.return_value = 2000
            response = client.get("/api/models")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        m = data["models"][0]
        assert "fits" in m
        assert "footprint_mb" in m
        assert "budget_mb" in m
        assert "reason" in m

    def test_loaded_true_when_model_is_running(self):
        models = [{"name": "llama3.2:latest", "size": 2 * 1024 ** 3, "modified_at": "", "digest": ""}]
        app, client = self._make_app_and_client(models)
        app.state.ollama_client.get_running_models.return_value = [{"name": "llama3.2:latest"}]

        from src.gpu.backends import CpuBackend

        cpu = CpuBackend(total_mb=32768, free_mb=16384)
        with patch("src.gpu.backends.detect", return_value=cpu):
            app.state.ollama_client.estimate_model_footprint.return_value = 2000
            response = client.get("/api/models")

        data = response.json()
        assert data["models"][0]["loaded"] is True

    def test_loaded_false_when_model_not_running(self):
        models = [{"name": "llama3.2:latest", "size": 2 * 1024 ** 3, "modified_at": "", "digest": ""}]
        app, client = self._make_app_and_client(models)
        app.state.ollama_client.get_running_models.return_value = []

        from src.gpu.backends import CpuBackend

        cpu = CpuBackend(total_mb=32768, free_mb=16384)
        with patch("src.gpu.backends.detect", return_value=cpu):
            app.state.ollama_client.estimate_model_footprint.return_value = 2000
            response = client.get("/api/models")

        data = response.json()
        assert data["models"][0]["loaded"] is False

    def test_fits_false_when_oversized(self):
        models = [{"name": "huge:70b", "size": 40 * 1024 ** 3, "modified_at": "", "digest": ""}]
        app, client = self._make_app_and_client(models)

        from src.gpu.backends import NvidiaBackend

        nvidia = NvidiaBackend(total_mb=8192, free_mb=4096)
        with patch("src.gpu.backends.detect", return_value=nvidia):
            # footprint 42 GB >> 4 GB free
            app.state.ollama_client.estimate_model_footprint.return_value = 43008
            response = client.get("/api/models")

        data = response.json()
        m = data["models"][0]
        assert m["fits"] is False
        assert m["reason"] is not None

    def test_fits_true_when_model_fits(self):
        models = [{"name": "llama3.2:3b", "size": 2 * 1024 ** 3, "modified_at": "", "digest": ""}]
        app, client = self._make_app_and_client(models)

        from src.gpu.backends import NvidiaBackend

        nvidia = NvidiaBackend(total_mb=8192, free_mb=8000)
        with patch("src.gpu.backends.detect", return_value=nvidia):
            app.state.ollama_client.estimate_model_footprint.return_value = 3500
            response = client.get("/api/models")

        data = response.json()
        m = data["models"][0]
        assert m["fits"] is True
        assert m["reason"] is None

    def test_fallback_on_gpu_detection_failure(self):
        models = [{"name": "llama3.2:3b", "size": 2 * 1024 ** 3, "modified_at": "", "digest": ""}]
        app, client = self._make_app_and_client(models)
        app.state.ollama_client.get_running_models.return_value = [{"name": "llama3.2:3b"}]

        with patch("src.gpu.backends.detect", side_effect=RuntimeError("gpu exploded")):
            response = client.get("/api/models")

        data = response.json()
        assert data["success"] is True
        # fallback: fits=True so UI doesn't block all models
        assert data["models"][0]["fits"] is True
        assert data["models"][0]["loaded"] is True
