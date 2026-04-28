"""Unit tests for GpuMonitor: subprocess parsing, TTL cache, graceful fallback."""

import json
import time
from unittest.mock import MagicMock, patch


class TestNoToolsAvailable:
    def test_returns_empty_list_when_neither_tool_found(self):
        from src.gpu_monitor import GpuMonitor

        monitor = GpuMonitor()
        with patch("src.gpu_monitor.shutil.which", return_value=None):
            result = monitor.get_gpu_info()
        assert result == []


class TestNvidiaSmi:
    _ONE_GPU = "0, NVIDIA GeForce RTX 3090, 24576, 4096, 20480, 62, 71"
    _TWO_GPUS = (
        "0, NVIDIA GeForce RTX 3090, 24576, 4096, 20480, 62, 71\n"
        "1, NVIDIA A100-SXM4-80GB, 81920, 20480, 61440, 88, 56"
    )

    def _run(self, stdout: str, returncode: int = 0):
        from src.gpu_monitor import GpuMonitor

        monitor = GpuMonitor()
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        with patch(
            "src.gpu_monitor.shutil.which",
            side_effect=lambda t: "/usr/bin/nvidia-smi" if t == "nvidia-smi" else None,
        ):
            with patch("src.gpu_monitor.subprocess.run", return_value=proc):
                return monitor.get_gpu_info()

    def test_parses_single_gpu(self):
        gpus = self._run(self._ONE_GPU)
        assert len(gpus) == 1
        g = gpus[0]
        assert g["id"] == 0
        assert g["name"] == "NVIDIA GeForce RTX 3090"
        assert g["vendor"] == "NVIDIA"
        assert g["vram_total_mb"] == 24576
        assert g["vram_used_mb"] == 4096
        assert g["vram_free_mb"] == 20480
        assert g["utilization_percent"] == 62
        assert g["temperature_c"] == 71

    def test_parses_two_gpus(self):
        gpus = self._run(self._TWO_GPUS)
        assert len(gpus) == 2
        assert gpus[1]["id"] == 1
        assert gpus[1]["name"] == "NVIDIA A100-SXM4-80GB"

    def test_nonzero_return_code_returns_empty(self):
        assert self._run("", returncode=1) == []

    def test_malformed_line_skipped(self):
        assert self._run("not,enough,fields") == []

    def test_subprocess_exception_returns_empty(self):
        from src.gpu_monitor import GpuMonitor

        monitor = GpuMonitor()
        with patch("src.gpu_monitor.shutil.which", return_value="/usr/bin/nvidia-smi"):
            with patch("src.gpu_monitor.subprocess.run", side_effect=OSError("no device")):
                assert monitor.get_gpu_info() == []


class TestRocmSmi:
    _ROCM_DATA = {
        "card0": {
            "VRAM Total Memory (B)": "17179869184",
            "VRAM Total Used Memory (B)": "4294967296",
            "GPU use (%)": "45",
            "Card Series": "AMD Radeon RX 6800 XT",
        }
    }

    def _run(self, stdout: str, returncode: int = 0):
        from src.gpu_monitor import GpuMonitor

        monitor = GpuMonitor()
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        with patch(
            "src.gpu_monitor.shutil.which",
            side_effect=lambda t: "/opt/rocm/bin/rocm-smi" if t == "rocm-smi" else None,
        ):
            with patch("src.gpu_monitor.subprocess.run", return_value=proc):
                return monitor.get_gpu_info()

    def test_parses_amd_gpu(self):
        gpus = self._run(json.dumps(self._ROCM_DATA))
        assert len(gpus) == 1
        g = gpus[0]
        assert g["vendor"] == "AMD"
        assert g["name"] == "AMD Radeon RX 6800 XT"
        assert g["vram_total_mb"] == 16384  # 17_179_869_184 // (1024 * 1024)
        assert g["vram_used_mb"] == 4096
        assert g["utilization_percent"] == 45
        assert g["temperature_c"] is None

    def test_nonzero_return_code_returns_empty(self):
        assert self._run("{}", returncode=1) == []

    def test_invalid_json_returns_empty(self):
        assert self._run("not valid json") == []

    def test_non_dict_card_entry_skipped(self):
        data = {
            "meta": "string_not_a_card",
            "card0": {
                "VRAM Total Memory (B)": "8589934592",
                "VRAM Total Used Memory (B)": "0",
                "GPU use (%)": "0",
            },
        }
        gpus = self._run(json.dumps(data))
        assert len(gpus) == 1  # "meta" entry is skipped; "card0" is included


class TestTtlCache:
    def test_second_call_within_ttl_skips_subprocess(self):
        from src.gpu_monitor import GpuMonitor

        monitor = GpuMonitor(ttl=60)
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "0, Test GPU, 8192, 1024, 7168, 30, 45"
        with patch("src.gpu_monitor.shutil.which", return_value="/usr/bin/nvidia-smi"):
            with patch("src.gpu_monitor.subprocess.run", return_value=proc) as mock_run:
                monitor.get_gpu_info()
                monitor.get_gpu_info()
                assert mock_run.call_count == 1

    def test_call_after_ttl_expiry_re_queries(self):
        from src.gpu_monitor import GpuMonitor

        monitor = GpuMonitor(ttl=0.01)  # 10 ms TTL
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "0, Test GPU, 8192, 1024, 7168, 30, 45"
        with patch("src.gpu_monitor.shutil.which", return_value="/usr/bin/nvidia-smi"):
            with patch("src.gpu_monitor.subprocess.run", return_value=proc) as mock_run:
                monitor.get_gpu_info()
                time.sleep(0.02)
                monitor.get_gpu_info()
                assert mock_run.call_count == 2
