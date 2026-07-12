"""GPU backend detection for model-fit estimation (MM-1).

Each backend exposes ``backend_name``, ``memory_model``, ``total_mb``, and
``free_mb``.  ``detect()`` probes hardware in order (NVIDIA → Apple → CPU)
and returns the first responding backend.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
from typing import Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class GpuBackend(Protocol):
    backend_name: str
    memory_model: Literal["dedicated", "shared"]
    total_mb: int
    free_mb: int


class NvidiaBackend:
    """Dedicated VRAM via nvidia-smi (sums across all GPUs)."""

    backend_name: str = "NVIDIA"
    memory_model: Literal["dedicated", "shared"] = "dedicated"

    def __init__(self, total_mb: int, free_mb: int) -> None:
        self.total_mb = total_mb
        self.free_mb = free_mb

    @classmethod
    def probe(cls) -> NvidiaBackend | None:
        if not shutil.which("nvidia-smi"):
            return None
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.total,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return None
            total = free = 0
            for line in result.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    total += int(parts[0])
                    free += int(parts[1])
            if total == 0:
                return None
            return cls(total, free)
        except Exception:
            logger.debug("nvidia-smi probe failed", exc_info=True)
            return None


class AmdBackend:
    """Dedicated VRAM via rocm-smi — not yet implemented."""

    backend_name: str = "AMD"
    memory_model: Literal["dedicated", "shared"] = "dedicated"

    def __init__(self, total_mb: int, free_mb: int) -> None:
        self.total_mb = total_mb
        self.free_mb = free_mb

    @classmethod
    def probe(cls) -> AmdBackend | None:
        # rocm-smi parsing is pending; fall through to next backend
        return None


class AppleBackend:
    """Shared unified memory on Apple Silicon via sysctl."""

    backend_name: str = "Apple"
    memory_model: Literal["dedicated", "shared"] = "shared"

    def __init__(self, total_mb: int, free_mb: int) -> None:
        self.total_mb = total_mb
        self.free_mb = free_mb

    @classmethod
    def probe(cls) -> AppleBackend | None:
        if platform.system() != "Darwin":
            return None
        try:
            result = subprocess.run(
                ["sysctl", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode != 0:
                return None
            total_bytes = int(result.stdout.strip().split(":")[1].strip())
            total_mb = total_bytes // (1024 * 1024)
            return cls(total_mb, total_mb)  # free = total; OS manages the pool
        except Exception:
            logger.debug("Apple sysctl probe failed", exc_info=True)
            return None


class CpuBackend:
    """Shared system RAM via psutil (fallback for CPU-only inference)."""

    backend_name: str = "CPU"
    memory_model: Literal["dedicated", "shared"] = "shared"

    def __init__(self, total_mb: int, free_mb: int) -> None:
        self.total_mb = total_mb
        self.free_mb = free_mb

    @classmethod
    def probe(cls) -> CpuBackend:
        try:
            import psutil

            mem = psutil.virtual_memory()
            total_mb = mem.total // (1024 * 1024)
            free_mb = mem.available // (1024 * 1024)
        except ImportError:
            total_mb = free_mb = 0
        return cls(total_mb, free_mb)


def detect(force: str = "auto") -> GpuBackend:
    """Return the best available GPU backend.

    *force* maps to one of the GPU_BACKEND config values:
    ``auto`` probes NVIDIA → AMD → Apple → CPU.
    Any other value selects that backend directly (falling back to CPU).
    """
    if force == "nvidia":
        nvidia_backend = NvidiaBackend.probe()
        return nvidia_backend if nvidia_backend is not None else CpuBackend.probe()
    if force == "amd":
        return CpuBackend.probe()  # AMD detection not yet implemented
    if force == "apple":
        apple_backend = AppleBackend.probe()
        return apple_backend if apple_backend is not None else CpuBackend.probe()
    if force == "cpu":
        return CpuBackend.probe()

    # auto: probe in priority order
    nvidia = NvidiaBackend.probe()
    if nvidia is not None:
        logger.info("GPU backend: NVIDIA (%d MB total, %d MB free)", nvidia.total_mb, nvidia.free_mb)
        return nvidia
    apple = AppleBackend.probe()
    if apple is not None:
        logger.info("GPU backend: Apple unified memory (%d MB total)", apple.total_mb)
        return apple
    cpu = CpuBackend.probe()
    logger.info("GPU backend: CPU RAM (%d MB total, %d MB free)", cpu.total_mb, cpu.free_mb)
    return cpu
