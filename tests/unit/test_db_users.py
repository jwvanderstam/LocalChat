"""
Tests for src/db/users.py (UsersMixin)

Covers:
  - create_user: DB unavailable raises, returns UUID string, lowercases username
  - seed_admin_user: DB unavailable raises, seeded vs. already-exists (ON CONFLICT)
  - get_user_by_username: not found, found, excludes soft-deleted (deleted_at IS NULL filter)
  - get_user_by_id: not found, found
  - list_users: DB unavailable returns [], returns list of dicts
  - count_users: DB unavailable returns 0, returns count
  - update_user: no allowed fields is a no-op, DB unavailable raises, updates and returns bool
  - delete_user (soft-delete): DB unavailable raises, sets deleted_at/deleted_by, filters live rows
  - purge_user: blocked when workspace memberships exist, hard-deletes otherwise
  - verify_user_password: unknown user, inactive user, wrong password, correct password
  - hash_user_password: produces a verifiable Werkzeug hash
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers — build a mixin instance with a mocked get_connection
# ---------------------------------------------------------------------------

def _make_conn_ctx(fetchone_return=None, fetchall_return=None, rowcount=0):
    """Return (conn, cur) mocks shaped like psycopg3's context-manager API."""
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_return
    cur.fetchall.return_value = fetchall_return or []
    cur.rowcount = rowcount
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    return conn, cur


def _users_mixin(connected=True, **conn_kwargs):
    from src.db.users import UsersMixin

    conn, cur = _make_conn_ctx(**conn_kwargs)
    m = UsersMixin()
    m.is_connected = connected
    m.get_connection = MagicMock(return_value=conn)
    return m, conn, cur


# ===========================================================================
# create_user
# ===========================================================================

class TestCreateUser:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _users_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.create_user("alice", "hash")

    def test_returns_string_id(self):
        uid = uuid.uuid4()
        m, _, cur = _users_mixin(fetchone_return=(uid,))
        result = m.create_user("alice", "hash")
        assert result == str(uid)

    def test_lowercases_and_strips_username(self):
        m, _, cur = _users_mixin(fetchone_return=(uuid.uuid4(),))
        m.create_user("  Alice  ", "hash")
        params = cur.execute.call_args[0][1]
        assert params[0] == "alice"

    def test_passes_email_and_role(self):
        m, _, cur = _users_mixin(fetchone_return=(uuid.uuid4(),))
        m.create_user("bob", "hash", email="bob@example.com", role="admin")
        params = cur.execute.call_args[0][1]
        assert params[1] == "bob@example.com"
        assert params[3] == "admin"


# ===========================================================================
# seed_admin_user
# ===========================================================================

class TestSeedAdminUser:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _users_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.seed_admin_user("admin", "hash")

    def test_seeds_when_no_conflict(self, caplog):
        m, _, cur = _users_mixin(rowcount=1)
        m.seed_admin_user("admin", "hash")
        cur.execute.assert_called_once()

    def test_no_op_log_when_already_exists(self):
        m, _, cur = _users_mixin(rowcount=0)
        # Should not raise even though the row already existed (ON CONFLICT DO NOTHING).
        m.seed_admin_user("admin", "hash")
        cur.execute.assert_called_once()


# ===========================================================================
# get_user_by_username / get_user_by_id
# ===========================================================================

class TestGetUserByUsername:
    def test_returns_none_when_db_unavailable(self):
        m, _, _ = _users_mixin(connected=False)
        assert m.get_user_by_username("alice") is None

    def test_returns_none_when_not_found(self):
        m, _, _ = _users_mixin(fetchone_return=None)
        assert m.get_user_by_username("unknown") is None

    def test_returns_user_dict_when_found(self):
        from datetime import datetime
        uid = uuid.uuid4()
        m, _, cur = _users_mixin(
            fetchone_return=(uid, "alice", "alice@example.com", "hash", True, "user", datetime(2025, 1, 1))
        )
        result = m.get_user_by_username("alice")
        assert result["id"] == str(uid)
        assert result["username"] == "alice"
        assert result["is_active"] is True

    def test_query_filters_soft_deleted_rows(self):
        m, _, cur = _users_mixin(fetchone_return=None)
        m.get_user_by_username("alice")
        query = cur.execute.call_args[0][0]
        assert "deleted_at IS NULL" in query

    def test_lowercases_and_strips_username(self):
        m, _, cur = _users_mixin(fetchone_return=None)
        m.get_user_by_username("  Alice  ")
        params = cur.execute.call_args[0][1]
        assert params[0] == "alice"


class TestGetUserById:
    def test_returns_none_when_db_unavailable(self):
        m, _, _ = _users_mixin(connected=False)
        assert m.get_user_by_id("some-id") is None

    def test_returns_none_when_not_found(self):
        m, _, _ = _users_mixin(fetchone_return=None)
        assert m.get_user_by_id("missing-id") is None

    def test_returns_user_dict_when_found(self):
        from datetime import datetime
        uid = uuid.uuid4()
        m, _, cur = _users_mixin(
            fetchone_return=(uid, "bob", None, "hash", True, "admin", datetime(2025, 1, 1))
        )
        result = m.get_user_by_id(str(uid))
        assert result["username"] == "bob"
        assert result["role"] == "admin"

    def test_query_filters_soft_deleted_rows(self):
        m, _, cur = _users_mixin(fetchone_return=None)
        m.get_user_by_id("some-id")
        query = cur.execute.call_args[0][0]
        assert "deleted_at IS NULL" in query


# ===========================================================================
# list_users / count_users
# ===========================================================================

class TestListUsers:
    def test_returns_empty_when_db_unavailable(self):
        m, _, _ = _users_mixin(connected=False)
        assert m.list_users() == []

    def test_returns_list_of_dicts(self):
        from datetime import datetime
        uid = uuid.uuid4()
        m, _, cur = _users_mixin(
            fetchall_return=[(uid, "alice", "a@example.com", "hash", True, "user", datetime(2025, 1, 1))]
        )
        result = m.list_users()
        assert len(result) == 1
        assert result[0]["username"] == "alice"

    def test_query_filters_soft_deleted_rows(self):
        m, _, cur = _users_mixin(fetchall_return=[])
        m.list_users()
        query = cur.execute.call_args[0][0]
        assert "deleted_at IS NULL" in query


class TestCountUsers:
    def test_returns_zero_when_db_unavailable(self):
        m, _, _ = _users_mixin(connected=False)
        assert m.count_users() == 0

    def test_returns_count_from_db(self):
        m, _, cur = _users_mixin(fetchone_return=(3,))
        assert m.count_users() == 3

    def test_query_filters_soft_deleted_rows(self):
        m, _, cur = _users_mixin(fetchone_return=(0,))
        m.count_users()
        query = cur.execute.call_args[0][0]
        assert "deleted_at IS NULL" in query


# ===========================================================================
# update_user
# ===========================================================================

class TestUpdateUser:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _users_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.update_user("uid", role="admin")

    def test_returns_false_when_no_allowed_fields(self):
        m, _, cur = _users_mixin()
        result = m.update_user("uid", not_a_real_field="x")
        assert result is False
        m.get_connection.assert_not_called()

    def test_ignores_disallowed_fields(self):
        m, _, cur = _users_mixin(rowcount=1)
        m.update_user("uid", role="admin", username="hacker")
        query = cur.execute.call_args[0][0]
        assert "username" not in query
        assert "role" in query

    def test_returns_true_when_row_updated(self):
        m, _, cur = _users_mixin(rowcount=1)
        assert m.update_user("uid", is_active=False) is True

    def test_returns_false_when_no_row_matched(self):
        m, _, cur = _users_mixin(rowcount=0)
        assert m.update_user("uid", is_active=False) is False


# ===========================================================================
# delete_user (soft delete) / purge_user (hard delete)
# ===========================================================================

class TestDeleteUser:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _users_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.delete_user("uid")

    def test_sets_deleted_at_and_deleted_by_not_hard_delete(self):
        m, _, cur = _users_mixin(rowcount=1)
        m.delete_user("uid", deleted_by="admin-id")
        query = cur.execute.call_args[0][0]
        assert "UPDATE users SET deleted_at" in query
        assert "DELETE FROM" not in query
        params = cur.execute.call_args[0][1]
        assert params == ("admin-id", "uid")

    def test_filters_to_live_rows_only(self):
        m, _, cur = _users_mixin(rowcount=1)
        m.delete_user("uid")
        query = cur.execute.call_args[0][0]
        assert "deleted_at IS NULL" in query

    def test_returns_true_when_row_retired(self):
        m, _, cur = _users_mixin(rowcount=1)
        assert m.delete_user("uid") is True

    def test_returns_false_when_already_deleted(self):
        m, _, cur = _users_mixin(rowcount=0)
        assert m.delete_user("uid") is False


class TestPurgeUser:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _users_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.purge_user("uid")

    def test_blocked_when_workspace_memberships_exist(self):
        m, _, cur = _users_mixin(fetchone_return=(1,))
        result = m.purge_user("uid")
        assert result is False
        # Only the membership-check SELECT should run, not a DELETE.
        assert cur.execute.call_count == 1

    def test_hard_deletes_when_no_memberships(self):
        m, _, cur = _users_mixin()
        cur.fetchone.return_value = None  # no membership row found
        cur.rowcount = 1
        result = m.purge_user("uid")
        assert result is True
        delete_query = cur.execute.call_args_list[-1][0][0]
        assert "DELETE FROM users" in delete_query

    def test_returns_false_when_delete_matches_no_row(self):
        m, _, cur = _users_mixin()
        cur.fetchone.return_value = None
        cur.rowcount = 0
        assert m.purge_user("uid") is False


# ===========================================================================
# verify_user_password
# ===========================================================================

class TestVerifyUserPassword:
    def test_returns_none_when_user_not_found(self):
        m, _, cur = _users_mixin(fetchone_return=None)
        assert m.verify_user_password("nobody", "pw") is None

    def test_returns_none_when_user_inactive(self):
        from datetime import datetime
        uid = uuid.uuid4()
        m, _, cur = _users_mixin(
            fetchone_return=(uid, "alice", None, "hash", False, "user", datetime(2025, 1, 1))
        )
        assert m.verify_user_password("alice", "pw") is None

    def test_returns_none_when_password_wrong(self):
        from datetime import datetime

        from src.db.users import hash_user_password
        uid = uuid.uuid4()
        real_hash = hash_user_password("correct-password")
        m, _, cur = _users_mixin(
            fetchone_return=(uid, "alice", None, real_hash, True, "user", datetime(2025, 1, 1))
        )
        assert m.verify_user_password("alice", "wrong-password") is None

    def test_returns_user_dict_without_hash_when_password_correct(self):
        from datetime import datetime

        from src.db.users import hash_user_password
        uid = uuid.uuid4()
        real_hash = hash_user_password("correct-password")
        m, _, cur = _users_mixin(
            fetchone_return=(uid, "alice", None, real_hash, True, "user", datetime(2025, 1, 1))
        )
        result = m.verify_user_password("alice", "correct-password")
        assert result is not None
        assert result["username"] == "alice"
        assert "hashed_password" not in result


class TestHashUserPassword:
    def test_produces_a_verifiable_hash(self):
        from werkzeug.security import check_password_hash

        from src.db.users import hash_user_password
        hashed = hash_user_password("s3cret")
        assert hashed != "s3cret"
        assert check_password_hash(hashed, "s3cret")
        assert not check_password_hash(hashed, "wrong")
