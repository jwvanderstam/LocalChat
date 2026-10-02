"""P2-5 — the runtime lock installs CPU-only torch.

`requirements.in` names the PyTorch CPU index and relies on PEP 440 ordering `+cpu` above the
plain release, so torch is not pinned there. If that index ever lags a release, pip-compile
falls back to PyPI's CUDA build without a word, and the image regains gigabytes of nvidia-*
packages for a container that never has a GPU. This reads the lock and says so.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_LOCK = Path(__file__).resolve().parents[2] / "requirements.txt"


def _pins() -> dict[str, str]:
    pins = {}
    for line in _LOCK.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_.\-\[\],]+)==(\S+)$", line.strip())
        if match:
            pins[match.group(1).split("[")[0].lower()] = match.group(2)
    return pins


def test_torch_is_the_cpu_build():
    assert _pins()["torch"].endswith("+cpu"), _pins()["torch"]


def test_no_gpu_runtime_is_pinned():
    gpu = sorted(
        name for name in _pins()
        if name.startswith(("nvidia-", "cuda-")) or name == "triton"
    )
    assert gpu == []


def test_the_lock_names_the_cpu_index():
    lines = {line.strip() for line in _LOCK.read_text(encoding="utf-8").splitlines()}
    assert "--extra-index-url https://download.pytorch.org/whl/cpu" in lines
