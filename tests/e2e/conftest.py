"""A LocalChat the browser can actually talk to.

The e2e suite used to require a server someone had started by hand on port 5000,
which is why it never ran anywhere but a developer's laptop. This starts one:
uvicorn in a subprocess, against the Postgres the integration job already
provides, with `OLLAMA_BASE_URL` pointed at TQ-2's stub instead of a GPU.

Everything the browser exercises is the real thing — templates, static JS, auth
cookies, SSE, ingest, pgvector retrieval. Only the model process is faked.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.utils.fake_ollama import FakeOllama

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Seeded by `_seed_admin_user()` on first boot against an empty database, and
#: left alone on every boot after that — so this password must not change
#: between runs sharing a database.
ADMIN_USERNAME = "e2e-admin"
ADMIN_PASSWORD = "e2e-admin-password-not-a-secret"

_STARTUP_TIMEOUT = 180.0


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def _serving(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return bool(response.status == 200)
    except (urllib.error.URLError, OSError):
        return False


@pytest.fixture(scope="session")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A bootstrapped LocalChat on a free port. Yields its base URL."""
    ollama = FakeOllama()
    ollama_url = ollama.start()

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    log_path = tmp_path_factory.mktemp("e2e") / "server.log"

    env = {
        **os.environ,
        "OLLAMA_BASE_URL": ollama_url,
        "ADMIN_USERNAME": ADMIN_USERNAME,
        "ADMIN_PASSWORD": ADMIN_PASSWORD,
        # `load_dotenv()` does not override the environment, so these win over a
        # developer's .env and the browser never reaches their real database.
        "APP_ENV": "development",
        "SECRET_KEY": "e2e-secret-key-32-characters-long!",
        "JWT_SECRET_KEY": "e2e-jwt-secret-key-32-characters!",
    }

    with log_path.open("w", encoding="utf-8") as log:
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app:create_uvicorn_app", "--factory",
             "--host", "127.0.0.1", "--port", str(port)],
            cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        )

        try:
            _wait_until_serving(server, base_url, log_path)
            yield base_url
        finally:
            server.terminate()
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                server.kill()
            ollama.stop()


def _wait_until_serving(server: subprocess.Popen[bytes], base_url: str,
                        log_path: Path) -> None:
    """Block until the login page answers, or fail with the server's own log.

    Bootstrap creates the schema and runs the migration chain before uvicorn binds,
    so a served page means a fully started application — not one still migrating.
    """
    deadline = time.monotonic() + _STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if server.poll() is not None:
            pytest.fail(f"server exited with {server.returncode}\n\n{_tail(log_path)}")
        if _serving(f"{base_url}/login"):
            return
        time.sleep(0.5)
    server.kill()
    pytest.fail(f"server did not serve /login within {_STARTUP_TIMEOUT:.0f}s\n\n{_tail(log_path)}")


def _tail(log_path: Path, lines: int = 40) -> str:
    try:
        return "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no server log)"


@pytest.fixture(scope="session")
def base_url(live_server: str) -> str:
    """What `page.goto("/")` resolves against — overrides pytest-base-url's."""
    return live_server
