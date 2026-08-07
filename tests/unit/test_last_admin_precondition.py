"""AUTH-2 — an installation must never be left without an admin.

The API allowed the last admin to demote, deactivate or delete themselves. The
result is an installation nobody can manage: no user administration, no model
management, no settings, recoverable only by editing the database by hand.

Enforced in the DB layer rather than the UI on purpose. A greyed-out button is a
courtesy; the precondition has to hold for any caller, including curl.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.users import LastAdminError, UsersMixin

ADMIN = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


class _Db(UsersMixin):
    """UsersMixin over a recording cursor, so the guard is exercised, not mocked away."""

    def __init__(self, *, role: str = "admin", admin_count: int = 1):
        self.is_connected = True
        self._role = role
        self._admin_count = admin_count
        self.executed: list[str] = []

    def get_user_by_id(self, user_id: str):
        return {"id": user_id, "username": "jo", "role": self._role}

    def count_live_admins(self) -> int:
        return self._admin_count

    def get_connection(self):
        cur = MagicMock()
        cur.rowcount = 1
        cur.execute.side_effect = lambda sql, *a: self.executed.append(sql)
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        outer = MagicMock()
        outer.__enter__.return_value = conn
        outer.__exit__.return_value = None
        return outer


@pytest.mark.unit
class TestLastAdminCannotBeRemoved:
    def test_demoting_the_last_admin_is_refused(self):
        with pytest.raises(LastAdminError):
            _Db(admin_count=1).update_user(ADMIN, role="user")

    def test_deactivating_the_last_admin_is_refused(self):
        with pytest.raises(LastAdminError):
            _Db(admin_count=1).update_user(ADMIN, is_active=False)

    def test_deleting_the_last_admin_is_refused(self):
        with pytest.raises(LastAdminError):
            _Db(admin_count=1).delete_user(ADMIN)

    def test_refusal_writes_nothing(self):
        """The guard must run before the UPDATE, not alongside it."""
        db = _Db(admin_count=1)
        with pytest.raises(LastAdminError):
            db.update_user(ADMIN, role="user")
        assert db.executed == []


@pytest.mark.unit
class TestOtherwiseUnchanged:
    """The negative space: the guard must not block ordinary administration."""

    def test_demoting_one_of_several_admins_is_allowed(self):
        assert _Db(admin_count=2).update_user(ADMIN, role="user") is True

    def test_deleting_one_of_several_admins_is_allowed(self):
        assert _Db(admin_count=2).delete_user(ADMIN) is True

    def test_deleting_a_non_admin_is_allowed_even_as_the_only_admin_exists(self):
        assert _Db(role="user", admin_count=1).delete_user(OTHER) is True

    def test_changing_an_admins_email_is_allowed(self):
        """Not every update is a demotion."""
        assert _Db(admin_count=1).update_user(ADMIN, email="a@b.c") is True

    def test_promoting_to_admin_is_allowed(self):
        assert _Db(role="user", admin_count=1).update_user(OTHER, role="admin") is True


@pytest.mark.unit
class TestRouteTranslatesTheRefusal:
    def _client(self, exc: Exception | None):
        from src.routes_fastapi.auth_routes import router

        state = MagicMock()
        state.testing = True
        state.db.is_connected = True
        if exc:
            state.db.update_user.side_effect = exc
            state.db.delete_user.side_effect = exc
        else:
            state.db.update_user.return_value = True
            state.db.delete_user.return_value = True
        state.db.get_user_by_id.return_value = {"id": ADMIN, "username": "jo", "role": "user"}
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.state = state
        return TestClient(app, raise_server_exceptions=False)

    def test_demotion_refusal_is_409_not_500(self):
        """The request is well-formed; the current state forbids it."""
        client = self._client(LastAdminError("Cannot remove the last remaining admin"))
        resp = client.put(f"/api/users/{ADMIN}", json={"role": "user"})
        assert resp.status_code == 409

    def test_refusal_message_reaches_the_caller(self):
        client = self._client(LastAdminError("Cannot remove the last remaining admin"))
        resp = client.put(f"/api/users/{ADMIN}", json={"role": "user"})
        assert "last remaining admin" in resp.json()["message"]

    def test_delete_refusal_is_409(self):
        client = self._client(LastAdminError("Cannot delete the last remaining admin"))
        assert client.delete(f"/api/users/{ADMIN}").status_code == 409

    def test_ordinary_update_still_succeeds(self):
        client = self._client(None)
        assert client.put(f"/api/users/{ADMIN}", json={"role": "user"}).status_code == 200


@pytest.mark.unit
class TestRowMapperCarriesRetirement:
    """_row_to_user maps positionally, so a newly selected column is silently dropped.

    That is exactly what happened: list_users gained a deleted_at column, the mapper
    ignored it, and every retired user came back looking live — the badge and the
    purge button were unreachable. Mocked route tests could not see it because they
    never produce a real row.
    """

    def test_eighth_column_becomes_deleted_at(self):
        from datetime import UTC, datetime

        from src.db.users import _row_to_user

        row = ("id", "jo", None, "hash", True, "user", None, datetime.now(UTC))
        assert _row_to_user(row)["deleted_at"] is not None

    def test_null_eighth_column_reads_as_live(self):
        from src.db.users import _row_to_user

        row = ("id", "jo", None, "hash", True, "user", None, None)
        assert _row_to_user(row)["deleted_at"] is None

    def test_seven_column_row_still_maps(self):
        """The single-row lookups select seven columns and must keep working."""
        from src.db.users import _row_to_user

        assert _row_to_user(("id", "jo", None, "hash", True, "user", None))["username"] == "jo"


@pytest.mark.unit
class TestRetiredUsersRemainVisible:
    def test_listing_can_include_retired_users(self):
        """A retired user still owns documents; hiding them makes the list lie."""
        from src.routes_fastapi.auth_routes import router

        state = MagicMock()
        state.testing = True
        state.db.is_connected = True
        state.db.list_users.return_value = []
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.state = state
        client = TestClient(app, raise_server_exceptions=False)
        client.get("/api/users?include_retired=true")
        assert state.db.list_users.call_args.kwargs["include_retired"] is True

    def test_listing_excludes_them_by_default(self):
        from src.routes_fastapi.auth_routes import router

        state = MagicMock()
        state.testing = True
        state.db.is_connected = True
        state.db.list_users.return_value = []
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.state = state
        client = TestClient(app, raise_server_exceptions=False)
        client.get("/api/users")
        assert state.db.list_users.call_args.kwargs["include_retired"] is False
