"""SEC-1 — DEMO_MODE is gone, and setting it does nothing.

It disabled *authorisation* when what it meant to limit was *reachability*. A safety
flag implemented at the wrong layer became the risk it was introduced to reduce: one
`.env` with `DEMO_MODE=true` on a host with a network interface exposed every route,
including the 27 admin ones.

Asserting the variable is inert matters more than asserting the constant is absent —
a leftover `DEMO_MODE=true` in someone's `.env` must be a no-op, not a surprise.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.unit
class TestDemoModeIsRemoved:
    def test_config_has_no_demo_mode_constant(self):
        from src import config

        assert not hasattr(config, "DEMO_MODE")

    def test_setting_the_env_var_does_not_disable_authorisation(self):
        """The property that matters: a stale .env entry is inert."""
        from src.routes_fastapi.document_routes import router

        state = MagicMock()
        state.db.is_connected = True
        state.db.get_workspace_member_role.return_value = None
        state.db.get_default_workspace_id.return_value = "ws-1"
        app = FastAPI()
        app.include_router(router, prefix="/api/documents")
        app.state = state
        client = TestClient(app, raise_server_exceptions=False)

        with patch.dict(os.environ, {"DEMO_MODE": "true"}), \
             patch("src.security_fastapi._ADMIN_PASSWORD_RAW", "set-so-rbac-is-live"):
            resp = client.get("/api/documents/list")
        assert resp.status_code == 401

    def test_status_payload_no_longer_advertises_demo_mode(self):
        from src.routes_fastapi import settings_routes

        source = __import__("inspect").getsource(settings_routes)
        assert "demo_mode" not in source


@pytest.mark.unit
class TestEmptyAdminPasswordNoLongerBypasses:
    """The other branch SEC-1 removed.

    It existed because an empty password meant no account existed, so refusing every
    request would have locked everyone out. An admin is now always seeded, so the
    premise is gone — and with it a default install that ran with all authorisation
    off, including /admin.
    """

    def test_empty_admin_password_does_not_bypass(self):
        from src.routes_fastapi.document_routes import router

        state = MagicMock()
        state.db.is_connected = True
        state.db.get_workspace_member_role.return_value = None
        state.db.get_default_workspace_id.return_value = "ws-1"
        app = FastAPI()
        app.include_router(router, prefix="/api/documents")
        app.state = state
        client = TestClient(app, raise_server_exceptions=False)

        with patch("src.security_fastapi._ADMIN_PASSWORD_RAW", ""):
            resp = client.get("/api/documents/list")
        assert resp.status_code == 401


@pytest.mark.unit
class TestNoBypassRemains:
    """TQ-1b removed the last one. This class exists to keep it removed.

    It used to assert the opposite — that `app.state.testing` bypassed authorisation —
    and predicted its own replacement. The bypass was worse than its call count
    suggested: `getattr(state, "testing", False)` reads truthy on a `MagicMock`, so it
    was active in every test with a mocked app state, whether that test asked for it or
    not. Authorisation-off was the default, and 290 tests depended on it without saying
    so.
    """

    def test_the_bypass_helpers_are_gone(self):
        import src.security_fastapi as sec

        assert not hasattr(sec, "_is_rbac_bypassed")
        assert not hasattr(sec, "_is_testing")

    def test_no_module_consults_a_testing_flag(self):
        """A re-added bypass would most likely wear the same name."""
        import subprocess
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        hits = subprocess.run(
            ["git", "grep", "-n", "-e", r"state\.testing", "-e", r'state, "testing"', "--", "src/"],
            cwd=root, capture_output=True, text=True,
        ).stdout.strip()
        assert not hits, f"src/ reads a testing flag again:\n{hits}"


@pytest.mark.unit
class TestSeedGeneratesAPasswordWhenNoneIsSet:
    """Seed-and-start: a fresh clone comes up with authorisation ON, not off."""

    def _run_seed(self, *, admin_password: str, app_env: str):
        from src import app_bootstrap

        db = MagicMock()
        with patch.object(app_bootstrap.config, "ADMIN_PASSWORD", admin_password), \
             patch.object(app_bootstrap.config, "APP_ENV", app_env), \
             patch.object(app_bootstrap.config, "ADMIN_USERNAME", "admin"):
            app_bootstrap._seed_admin_user(db)
        return db

    def test_seeds_with_a_generated_password_when_none_is_configured(self):
        db = self._run_seed(admin_password="", app_env="development")
        db.seed_admin_user.assert_called_once()

    def test_does_not_seed_a_generated_password_in_production(self):
        """The generated value is logged; that is a developer-machine trade only."""
        db = self._run_seed(admin_password="", app_env="production")
        db.seed_admin_user.assert_not_called()

    def test_uses_the_configured_password_when_present(self):
        db = self._run_seed(admin_password="chosen-by-the-operator", app_env="production")
        db.seed_admin_user.assert_called_once()
