"""
GPU Monitor
===========

Hardware GPU detection via system tools (nvidia-smi, rocm-smi).
Results are TTL-cached to avoid spawning subprocesses on every call.

Supports NVIDIA GPUs (via ``nvidia-smi``) and AMD GPUs (via ``rocm-smi``).
Returns an empty list when neither tool is available.

Example:
    >>> from src.gpu_monitor import GpuMonitor
    >>> monitor = GpuMonitor()
    >>> gpus = monitor.get_gpu_info()
    >>> for gpu in gpus:
    ...     print(gpu['name'], gpu['vram_total_mb'], 'MB')
"""

import json
import shutil
import subprocess
import time
from typing import Any

from .utils.logging_config import get_logger

logger = get_logger(__name__)


class GpuMonitor:
    """
    Detects available GPUs and returns per-GPU hardware statistics.

    Results are cached for ``ttl`` seconds (default 30) to avoid
    spawning subprocesses on every admin-dashboard refresh.  Tries
    NVIDIA first (via ``nvidia-smi``), then AMD (via ``rocm-smi``).
    Returns an empty list when neither tool is found or both fail.

    Each result entry contains:
        ``id``, ``name``, ``vendor``, ``vram_total_mb``, ``vram_used_mb``,
        ``vram_free_mb``, ``utilization_percent``, ``temperature_c``.

    Args:
        ttl: Seconds to cache results before re-querying (default: 30).
    """

    def __init__(self, ttl: float = 30.0) -> None:
        self._ttl = ttl
        self._cache: list[dict[str, Any]] = []
        self._cache_time: float = 0.0

    def get_gpu_info(self) -> list[dict[str, Any]]:
        """
        Return per-GPU hardware stats, refreshing after TTL expires.

        Returns:
            List of GPU info dicts (one per physical GPU), or empty list.
        """
        now = time.monotonic()
        if self._cache is not None and (now - self._cache_time) < self._ttl:
            return self._cache
        gpus = self._get_nvidia_gpu_info() or self._get_amd_gpu_info()
        self._cache = gpus
        self._cache_time = now
        return gpus

    def _get_nvidia_gpu_info(self) -> list[dict[str, Any]]:
        """Query ``nvidia-smi`` for per-GPU stats."""
        if not shutil.which("nvidia-smi"):
            return []
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.total,memory.used,"
                    "memory.free,utilization.gpu,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                logger.debug("nvidia-smi exited with code %d", result.returncode)
                return []
            gpus: list[dict[str, Any]] = []
            for line in result.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 7:
                    continue
                try:
                    gpus.append({
                        "id": int(parts[0]),
                        "name": parts[1],
                        "vendor": "NVIDIA",
                        "vram_total_mb": int(parts[2]),
                        "vram_used_mb": int(parts[3]),
                        "vram_free_mb": int(parts[4]),
                        "utilization_percent": int(parts[5]),
                        "temperature_c": int(parts[6]),
                    })
                except (ValueError, IndexError) as exc:
                    logger.debug("Skipping malformed nvidia-smi line: %s (%s)", line, exc)
            return gpus
        except Exception as exc:
            logger.debug("nvidia-smi query failed: %s", exc)
            return []

    def _get_amd_gpu_info(self) -> list[dict[str, Any]]:
        """Query ``rocm-smi`` for per-GPU stats."""
        if not shutil.which("rocm-smi"):
            return []
        try:
            result = subprocess.run(
                ["rocm-smi", "--showmeminfo", "vram", "--showuse", "--json"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                logger.debug("rocm-smi exited with code %d", result.returncode)
                return []
            data = json.loads(result.stdout)
            gpus: list[dict[str, Any]] = []
            for idx, (_, card_val) in enumerate(data.items()):
                if not isinstance(card_val, dict):
                    continue
                total_mb = int(card_val.get("VRAM Total Memory (B)", 0)) // (1024 * 1024)
                used_mb = int(card_val.get("VRAM Total Used Memory (B)", 0)) // (1024 * 1024)
                try:
                    util = int(float(str(card_val.get("GPU use (%)", "0")).rstrip("%")))
                except (ValueError, TypeError):
                    util = 0
                gpus.append({
                    "id": idx,
                    "name": card_val.get("Card Series", card_val.get("GPU ID", f"AMD GPU {idx}")),
                    "vendor": "AMD",
                    "vram_total_mb": total_mb,
                    "vram_used_mb": used_mb,
                    "vram_free_mb": max(0, total_mb - used_mb),
                    "utilization_percent": util,
                    "temperature_c": None,
                })
            return gpus
        except Exception as exc:
            logger.debug("rocm-smi query failed: %s", exc)
            return []
