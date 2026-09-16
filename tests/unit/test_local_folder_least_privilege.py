"""P0-3 — the local_folder connector reaches only where the installation allows.

Audit finding C4: any user could create a workspace, become its owner, and create a
`local_folder` connector on any path the server process could read — `/etc` was
reproduced — whose contents were then ingested and answered from.

Decision D3 keeps the feature at least privilege: creating or reconfiguring one
requires a *global admin*, and its path must resolve inside `CONNECTOR_LOCAL_ROOTS`.
The empty default disables the type, so an installation that never configures it is
not exposed by the feature existing.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.connectors.local_folder import LocalFolderConnector, resolve_allowed_root
from src.security_fastapi import create_access_token

USER = "33333333-3333-3333-3333-333333333333"
WS = "11111111-1111-1111-1111-111111111111"


def _auth(role: str = "user") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(USER, {'role': role})}"}


@pytest.fixture
def allowed_root(tmp_path, monkeypatch):
    """One configured root with a real directory inside it."""
    root = tmp_path / "corpus"
    (root / "inner").mkdir(parents=True)
    monkeypatch.setattr("src.config.CONNECTOR_LOCAL_ROOTS", [str(root)])
    return root


@pytest.mark.unit
class TestTheAllowlistIsTheWholePermission:
    def test_an_empty_allowlist_disables_the_type(self, tmp_path, monkeypatch):
        """The default is off, not unrestricted — otherwise the feature is C4 again."""
        monkeypatch.setattr("src.config.CONNECTOR_LOCAL_ROOTS", [])
        assert resolve_allowed_root(str(tmp_path)) is None

    def test_a_path_inside_a_root_is_allowed(self, allowed_root):
        assert resolve_allowed_root(str(allowed_root / "inner")) == os.path.realpath(
            str(allowed_root)
        )

    def test_the_root_itself_is_allowed(self, allowed_root):
        assert resolve_allowed_root(str(allowed_root)) is not None

    def test_a_system_directory_is_refused(self, allowed_root):
        """The path the audit actually reproduced."""
        assert resolve_allowed_root("/etc") is None

    def test_dot_dot_cannot_climb_out(self, allowed_root):
        escape = str(allowed_root / "inner" / ".." / ".." / "elsewhere")
        assert resolve_allowed_root(escape) is None

    def test_a_sibling_sharing_a_prefix_is_refused(self, tmp_path, monkeypatch):
        """commonpath compares components; startswith would admit this one."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs-secret").mkdir()
        monkeypatch.setattr("src.config.CONNECTOR_LOCAL_ROOTS", [str(tmp_path / "docs")])
        assert resolve_allowed_root(str(tmp_path / "docs-secret")) is None

    @pytest.mark.skipif(
        sys.platform == "win32", reason="symlink creation needs privilege on Windows"
    )
    def test_a_symlink_is_judged_by_where_it_lands(self, tmp_path, allowed_root):
        """Inside an allowed root, pointing out of it. realpath is why this fails."""
        outside = tmp_path / "outside"
        outside.mkdir()
        link = allowed_root / "escape"
        link.symlink_to(outside, target_is_directory=True)
        assert resolve_allowed_root(str(link)) is None

    def test_several_roots_are_each_honoured(self, tmp_path, monkeypatch):
        first, second = tmp_path / "a", tmp_path / "b"
        first.mkdir()
        second.mkdir()
        monkeypatch.setattr(
            "src.config.CONNECTOR_LOCAL_ROOTS", [str(first), str(second)]
        )
        assert resolve_allowed_root(str(second)) is not None


@pytest.mark.unit
class TestValidateConfigRefusesWhatTheAllowlistRefuses:
    def test_a_disallowed_path_is_a_validation_error(self, allowed_root):
        errors = LocalFolderConnector({"path": "/etc"}).validate_config()
        assert errors
        assert "CONNECTOR_LOCAL_ROOTS" in errors[0]

    def test_the_refusal_does_not_say_whether_the_directory_exists(self, allowed_root):
        """Differing answers would make the endpoint a filesystem probe."""
        real = LocalFolderConnector({"path": "/etc"}).validate_config()
        unreal = LocalFolderConnector(
            {"path": "/nonexistent-zzz/also-not-here"}
        ).validate_config()
        assert real == unreal

    def test_an_allowed_directory_validates(self, allowed_root):
        assert LocalFolderConnector({"path": str(allowed_root)}).validate_config() == []

    def test_an_allowed_but_absent_directory_still_fails(self, allowed_root):
        errors = LocalFolderConnector(
            {"path": str(allowed_root / "no-such-dir")}
        ).validate_config()
        assert errors
        assert "does not exist" in errors[0]

    def test_a_missing_path_is_still_required(self, allowed_root):
        assert LocalFolderConnector({}).validate_config() == ["'path' is required"]


def _client(member_role: str = "owner", global_role: str = "user"):
    from src.routes_fastapi.connector_routes import router

    state = MagicMock()
    state.db.is_connected = True
    state.db.get_workspace_member_role.return_value = member_role
    state.db.get_user_workspaces.return_value = [{"id": WS}]
    state.db.get_default_workspace_id.return_value = WS
    state.db.get_user_role.return_value = global_role
    state.db.is_token_revoked.return_value = False
    state.db.resolve_workspace_api_key.return_value = None
    state.connector_registry.available_types.return_value = ["local_folder"]
    state.connector_registry.get_class.return_value = LocalFolderConnector
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = state
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.unit
class TestCreatingOneIsAGlobalDecision:
    def test_a_workspace_owner_may_not_create_one(self, allowed_root):
        """Any user can create a workspace and own it, so owner is not a barrier."""
        client = _client(member_role="owner", global_role="user")
        resp = client.post(
            "/api/connectors",
            json={"connector_type": "local_folder", "config": {"path": str(allowed_root)}},
            headers=_auth(),
        )
        assert resp.status_code == 403
        assert not client.app.state.db.create_connector.called

    def test_an_admin_may_create_one_inside_an_allowed_root(self, allowed_root):
        client = _client(member_role="owner", global_role="admin")
        client.app.state.db.create_connector.return_value = "c-1"
        client.app.state.db.get_connector.return_value = {
            "id": "c-1",
            "connector_type": "local_folder",
            "config": {"path": str(allowed_root)},
            "workspace_id": WS,
        }
        with patch("src.routes_fastapi.connector_routes.require_admin_dep", return_value=USER):
            resp = client.post(
                "/api/connectors",
                json={
                    "connector_type": "local_folder",
                    "config": {"path": str(allowed_root)},
                },
                headers=_auth("admin"),
            )
        assert resp.status_code == 201
        assert client.app.state.db.create_connector.called

    def test_an_admin_may_not_create_one_outside_the_roots(self, allowed_root):
        """Admin is not a bypass for the allowlist — the two checks are independent."""
        client = _client(member_role="owner", global_role="admin")
        with patch("src.routes_fastapi.connector_routes.require_admin_dep", return_value=USER):
            resp = client.post(
                "/api/connectors",
                json={"connector_type": "local_folder", "config": {"path": "/etc"}},
                headers=_auth("admin"),
            )
        assert resp.status_code == 400
        assert not client.app.state.db.create_connector.called


@pytest.mark.unit
class TestReconfiguringIsTheSameDecision:
    """The other door: PUT wrote config with no validation and no admin check."""

    def test_an_owner_may_not_repoint_a_local_folder_connector(self, allowed_root):
        client = _client(member_role="owner", global_role="user")
        client.app.state.db.get_connector.return_value = {
            "id": "c-1",
            "connector_type": "local_folder",
            "config": {"path": str(allowed_root)},
            "workspace_id": WS,
        }
        resp = client.put(
            "/api/connectors/c-1", json={"config": {"path": "/etc"}}, headers=_auth()
        )
        assert resp.status_code == 403
        assert not client.app.state.db.update_connector.called

    def test_an_admin_repointing_outside_the_roots_is_refused(self, allowed_root):
        client = _client(member_role="owner", global_role="admin")
        client.app.state.db.get_connector.return_value = {
            "id": "c-1",
            "connector_type": "local_folder",
            "config": {"path": str(allowed_root)},
            "workspace_id": WS,
        }
        with patch("src.routes_fastapi.connector_routes.require_admin_dep", return_value=USER):
            resp = client.put(
                "/api/connectors/c-1", json={"config": {"path": "/etc"}}, headers=_auth("admin")
            )
        assert resp.status_code == 400
        assert not client.app.state.db.update_connector.called

    def test_an_admin_may_repoint_within_the_roots(self, allowed_root):
        client = _client(member_role="owner", global_role="admin")
        client.app.state.db.get_connector.return_value = {
            "id": "c-1",
            "connector_type": "local_folder",
            "config": {"path": str(allowed_root)},
            "workspace_id": WS,
        }
        client.app.state.db.update_connector.return_value = True
        with patch("src.routes_fastapi.connector_routes.require_admin_dep", return_value=USER):
            resp = client.put(
                "/api/connectors/c-1",
                json={"config": {"path": str(allowed_root / "inner")}},
                headers=_auth("admin"),
            )
        assert resp.status_code == 200
        assert client.app.state.db.update_connector.called

    def test_a_rename_does_not_require_admin(self, allowed_root):
        """Only a config change is the privileged decision; display_name is not."""
        client = _client(member_role="owner", global_role="user")
        client.app.state.db.update_connector.return_value = True
        client.app.state.db.get_connector.return_value = {
            "id": "c-1",
            "connector_type": "local_folder",
            "config": {"path": str(allowed_root)},
            "workspace_id": WS,
            "enabled": False,
        }
        resp = client.put(
            "/api/connectors/c-1", json={"display_name": "Renamed"}, headers=_auth()
        )
        assert resp.status_code == 200
