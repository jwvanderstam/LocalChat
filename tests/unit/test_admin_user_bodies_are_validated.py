"""R-10 (QP-9 review) — the admin user routes validate their bodies, and the last-admin rule counts active admins.

The three routes read raw dicts. An update took ``role`` and ``is_active`` as sent: any
role string was written, and ``"is_active": "false"`` slipped past the last-admin rule,
which tests ``is False``, and Postgres then stored it as false. A non-string username or
workspace id was a 500. And the rule counted deactivated admins, so the last *active*
admin could be deactivated while a deactivated one existed.

Against Postgres: ``tests/integration/test_admin_count_is_of_active_admins.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.services.users import LastAdminError, UsersService
from tests.utils.auth import admin_headers, authenticated_state

pytestmark = pytest.mark.unit

USER = "44444444-4444-4444-4444-444444444444"
WORKSPACE = "66666666-6666-6666-6666-666666666666"
PASSWORD = "a-long-enough-password"


def _client(*, active_admins: int = 1) -> tuple[TestClient, Any]:
    from src.routes_fastapi.auth_routes import router

    state = authenticated_state(role="admin")
    state.db.users.create.return_value = USER
    state.db.users.update.return_value = True
    state.db.users.count_active_admins.return_value = active_admins
    state.db.users.get_by_id.return_value = {"id": USER, "username": "jo", "role": "admin", "is_active": True}
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = state
    client = TestClient(app, raise_server_exceptions=True)
    client.headers.update(admin_headers())
    return client, state.db


class TestAnUpdateIsValidated:
    @pytest.mark.parametrize("value", ["false", 0, "no"], ids=["string", "zero", "word"])
    def test_is_active_that_is_not_a_boolean_never_reaches_the_last_admin_rule(self, value):
        """``"false"`` used to pass ``is False``, and Postgres stored it as false."""
        client, db = _client()
        resp = client.put(f"/api/users/{USER}", json={"is_active": value})
        assert (resp.status_code, resp.json()["message"], db.users.update.called) == (
            400, "is_active must be true or false", False)

    def test_a_role_that_does_not_exist_is_not_written(self):
        client, db = _client(active_admins=2)
        resp = client.put(f"/api/users/{USER}", json={"role": "superadmin"})
        assert (resp.status_code, resp.json()["message"], db.users.update.called) == (
            400, "role must be 'admin' or 'user'", False)

    @pytest.mark.parametrize("field", ["role", "is_active"])
    def test_null_for_a_column_that_has_no_null_is_refused(self, field):
        client, db = _client(active_admins=2)
        resp = client.put(f"/api/users/{USER}", json={field: None})
        assert (resp.status_code, resp.json()["message"], db.users.update.called) == (
            400, f"{field} cannot be null", False)

    def test_null_clears_the_email(self):
        """The negative space: email is the one field null is a value for."""
        client, db = _client()
        resp = client.put(f"/api/users/{USER}", json={"email": None})
        assert (resp.status_code, db.users.update.call_args.kwargs) == (200, {"email": None})

    def test_only_the_fields_sent_are_changed(self):
        client, db = _client(active_admins=2)
        resp = client.put(f"/api/users/{USER}", json={"is_active": False, "hashed_password": "x"})
        assert (resp.status_code, db.users.update.call_args.kwargs) == (200, {"is_active": False})

    def test_a_body_with_no_known_field_changes_nothing(self):
        client, db = _client()
        resp = client.put(f"/api/users/{USER}", json={"username": "someone-else"})
        assert (resp.status_code, resp.json()["message"], db.users.update.called) == (
            400, "No valid fields provided", False)

    def test_a_body_that_is_not_an_object_is_refused(self):
        client, db = _client()
        resp = client.put(f"/api/users/{USER}", json=["is_active", False])
        assert (resp.status_code, db.users.update.called) == (400, False)


class TestACreateIsValidated:
    def test_a_username_that_is_not_a_string_is_a_400_not_a_500(self):
        client, db = _client()
        resp = client.post("/api/users", json={"username": 123, "password": PASSWORD})
        assert (resp.status_code, db.users.create.called) == (400, False)

    def test_a_blank_username_is_refused(self):
        client, db = _client()
        resp = client.post("/api/users", json={"username": "  ", "password": PASSWORD})
        assert (resp.status_code, resp.json()["message"], db.users.create.called) == (
            400, "username is required", False)

    def test_a_workspace_role_that_does_not_exist_creates_nobody(self):
        client, db = _client()
        resp = client.post("/api/users", json={"username": "jo", "password": PASSWORD,
                                               "workspace_id": WORKSPACE, "workspace_role": "admin"})
        assert (resp.status_code, db.users.create.called) == (400, False)

    def test_a_valid_body_creates_the_user_and_the_membership(self):
        client, db = _client()
        resp = client.post("/api/users", json={"username": " jo ", "password": PASSWORD, "email": " ",
                                               "workspace_id": WORKSPACE, "workspace_role": "viewer"})
        created = db.users.create.call_args.kwargs
        assert (resp.status_code, created["username"], created["email"], db.members.add.call_args.args) == (
            201, "jo", None, (WORKSPACE, USER, "viewer"))


class TestAGrantIsValidated:
    def test_a_workspace_id_that_is_not_a_string_is_a_400_not_a_500(self):
        client, db = _client()
        resp = client.post(f"/api/users/{USER}/workspaces", json={"workspace_id": 5})
        assert (resp.status_code, resp.json()["message"], db.members.add.called) == (
            400, "workspace_id is required", False)

    def test_a_grant_defaults_to_editor(self):
        client, db = _client()
        resp = client.post(f"/api/users/{USER}/workspaces", json={"workspace_id": WORKSPACE})
        assert (resp.status_code, db.members.add.call_args.args) == (200, (WORKSPACE, USER, "editor"))


class _Users:
    def __init__(self, *, is_active: bool, active_admins: int):
        self._is_active = is_active
        self._active_admins = active_admins
        self.writes: list[str] = []

    def get_by_id(self, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "username": "jo", "role": "admin", "is_active": self._is_active}

    def count_active_admins(self) -> int:
        return self._active_admins

    def update(self, user_id: str, **fields: Any) -> bool:
        self.writes.append("update")
        return True

    def retire(self, user_id: str, deleted_by: str | None = None) -> bool:
        self.writes.append("retire")
        return True


def _service(*, is_active: bool, active_admins: int) -> tuple[UsersService, _Users]:
    users = _Users(is_active=is_active, active_admins=active_admins)
    return UsersService(SimpleNamespace(is_connected=True, users=users)), users


class TestTheLastAdminRuleCountsActiveAdmins:
    def test_the_last_active_admin_cannot_be_deactivated_beside_a_deactivated_one(self):
        """The repository counts one active admin; a deactivated one no longer makes it two."""
        service, users = _service(is_active=True, active_admins=1)
        with pytest.raises(LastAdminError):
            service.update_user(USER, {"is_active": False}, None)
        assert users.writes == []

    def test_a_deactivated_admin_can_be_retired_while_one_active_admin_remains(self):
        service, users = _service(is_active=False, active_admins=1)
        assert (service.retire_user(USER, actor="tester"), users.writes) == (True, ["retire"])

    def test_a_deactivated_admin_can_be_demoted_while_one_active_admin_remains(self):
        service, users = _service(is_active=False, active_admins=1)
        assert service.update_user(USER, {"role": "user"}, None) is not None


class TestTheRepositoryCountsActiveAdmins:
    def test_the_count_excludes_deactivated_and_retired_admins(self):
        from unittest.mock import MagicMock

        from src.db.users import UsersRepository

        cur = MagicMock()
        cur.fetchone.return_value = (3,)
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn = MagicMock()
        conn.cursor.return_value = cur
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        host = MagicMock(is_connected=True)
        host.get_connection = MagicMock(return_value=conn)

        count = UsersRepository(host).count_active_admins()
        sql = " ".join(cur.execute.call_args.args[0].split())
        assert (count, sql) == (
            3, "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active AND deleted_at IS NULL")
