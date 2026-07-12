"""
App Entry Point Tests
======================

Tests for app.py — create_uvicorn_app(), _is_db_reachable(), _ensure_db_running(),
and main(). All external I/O (sockets, subprocess, uvicorn) is mocked.
"""

import subprocess
from unittest.mock import Mock, patch

import pytest

from app import _ensure_db_running, _is_db_reachable, create_uvicorn_app, main

pytestmark = pytest.mark.unit


class TestIsDbReachable:
    def test_returns_true_when_socket_connects(self):
        with patch("app.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = Mock(return_value=Mock())
            mock_conn.return_value.__exit__ = Mock(return_value=None)

            assert _is_db_reachable("localhost", 5432) is True

    def test_returns_false_on_os_error(self):
        with patch("app.socket.create_connection", side_effect=OSError("refused")):
            assert _is_db_reachable("localhost", 5432) is False


class TestEnsureDbRunning:
    def test_returns_immediately_when_db_already_reachable(self):
        with patch("app._is_db_reachable", return_value=True), \
             patch("app.subprocess.run") as mock_run:
            _ensure_db_running()

        mock_run.assert_not_called()

    def test_starts_docker_compose_and_recovers_when_db_becomes_reachable(self):
        results = iter([False, False, True])
        with patch("app._is_db_reachable", side_effect=lambda h, p: next(results)), \
             patch("app.subprocess.run") as mock_run, \
             patch("app.time.monotonic", return_value=0.0), \
             patch("app.time.sleep") as mock_sleep:
            _ensure_db_running()

        mock_run.assert_called_once_with(["docker", "compose", "up", "-d", "db"], check=True)
        mock_sleep.assert_called_once()

    def test_exits_when_docker_is_not_installed(self):
        with patch("app._is_db_reachable", return_value=False), \
             patch("app.subprocess.run", side_effect=FileNotFoundError()), \
             patch("app.sys.exit", side_effect=SystemExit(1)) as mock_exit:
            with pytest.raises(SystemExit):
                _ensure_db_running()

        mock_exit.assert_called_once_with(1)

    def test_exits_when_docker_compose_up_fails(self):
        err = subprocess.CalledProcessError(returncode=1, cmd=["docker"])
        with patch("app._is_db_reachable", return_value=False), \
             patch("app.subprocess.run", side_effect=err), \
             patch("app.sys.exit", side_effect=SystemExit(1)) as mock_exit:
            with pytest.raises(SystemExit):
                _ensure_db_running()

        mock_exit.assert_called_once_with(1)

    def test_exits_when_db_never_becomes_reachable_within_deadline(self):
        times = iter([0.0, 10.0, 20.0, 31.0])
        with patch("app._is_db_reachable", return_value=False), \
             patch("app.subprocess.run") as mock_run, \
             patch("app.time.monotonic", side_effect=lambda: next(times)), \
             patch("app.time.sleep"), \
             patch("app.sys.exit", side_effect=SystemExit(1)) as mock_exit:
            with pytest.raises(SystemExit):
                _ensure_db_running()

        mock_run.assert_called_once()
        mock_exit.assert_called_once_with(1)


class TestCreateUvicornApp:
    def test_creates_app_and_runs_bootstrap(self):
        mock_app = Mock()
        with patch("src.app_fastapi.create_app", return_value=mock_app) as mock_create, \
             patch("src.app_bootstrap.bootstrap_app") as mock_bootstrap:
            result = create_uvicorn_app()

        mock_create.assert_called_once_with()
        mock_bootstrap.assert_called_once_with(mock_app)
        assert result is mock_app


class TestInitSecurity:
    def test_registers_rate_limit_exception_handler_when_not_testing(self):
        from fastapi import FastAPI
        from slowapi.errors import RateLimitExceeded

        from src.app_fastapi import _handle_rate_limit_exceeded, _init_security

        app = FastAPI()
        _init_security(app, testing=False)

        assert app.exception_handlers[RateLimitExceeded] is _handle_rate_limit_exceeded

    def test_skips_rate_limit_wiring_when_testing(self):
        from fastapi import FastAPI
        from slowapi.errors import RateLimitExceeded

        from src.app_fastapi import _init_security

        app = FastAPI()
        _init_security(app, testing=True)

        assert RateLimitExceeded not in app.exception_handlers


class TestHandleRateLimitExceeded:
    """src.app_fastapi._handle_rate_limit_exceeded — adapts slowapi's narrowly-typed
    handler to Starlette's generic (Request, Exception) -> Response signature."""

    def test_delegates_to_slowapi_handler_for_rate_limit_exceeded(self):
        from slowapi.errors import RateLimitExceeded

        from src.app_fastapi import _handle_rate_limit_exceeded

        mock_request = Mock()
        mock_response = Mock()
        exc = RateLimitExceeded(Mock())

        with patch("slowapi._rate_limit_exceeded_handler", return_value=mock_response) as mock_handler:
            result = _handle_rate_limit_exceeded(mock_request, exc)

        mock_handler.assert_called_once_with(mock_request, exc)
        assert result is mock_response

    def test_asserts_on_non_rate_limit_exception(self):
        from src.app_fastapi import _handle_rate_limit_exceeded

        with pytest.raises(AssertionError):
            _handle_rate_limit_exceeded(Mock(), ValueError("not a rate limit error"))


class TestMain:
    def test_starts_uvicorn_with_env_configured_host_and_port(self):
        with patch("app._ensure_db_running") as mock_ensure, \
             patch("uvicorn.run") as mock_run, \
             patch.dict("os.environ", {"SERVER_HOST": "0.0.0.0", "SERVER_PORT": "9000"}):
            main()

        mock_ensure.assert_called_once()
        mock_run.assert_called_once_with(
            "app:create_uvicorn_app",
            factory=True,
            host="0.0.0.0",
            port=9000,
            log_level="info",
            reload=False,
        )

    def test_uses_default_host_and_port_when_env_unset(self):
        with patch("app._ensure_db_running"), \
             patch("uvicorn.run") as mock_run, \
             patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("SERVER_HOST", None)
            os.environ.pop("SERVER_PORT", None)
            main()

        _, kwargs = mock_run.call_args
        assert kwargs["host"] == "localhost"
        assert kwargs["port"] == 5000

    def test_defaults_port_when_server_port_env_is_not_an_integer(self):
        with patch("app._ensure_db_running"), \
             patch("uvicorn.run") as mock_run, \
             patch.dict("os.environ", {"SERVER_PORT": "not-a-number"}):
            main()

        _, kwargs = mock_run.call_args
        assert kwargs["port"] == 5000

    def test_swallows_keyboard_interrupt(self):
        with patch("app._ensure_db_running"), \
             patch("uvicorn.run", side_effect=KeyboardInterrupt):
            main()  # must not raise

    def test_exits_with_status_1_on_server_error(self):
        with patch("app._ensure_db_running"), \
             patch("uvicorn.run", side_effect=RuntimeError("boom")), \
             patch("app.sys.exit", side_effect=SystemExit(1)) as mock_exit:
            with pytest.raises(SystemExit):
                main()

        mock_exit.assert_called_once_with(1)
