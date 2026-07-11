"""
Tests for src/db/workspaces.py (WorkspacesMixin)

Covers:
  - create_workspace: DB unavailable raises, returns UUID string, truncates name
  - get_workspace: not found, found, filters soft-deleted rows
  - list_workspaces: DB unavailable returns [], returns list with doc/conversation counts
  - get_default_workspace_id: DB unavailable returns None, returns oldest workspace id
  - update_workspace: DB unavailable raises, no fields is a no-op, partial update, returns bool
  - delete_workspace (soft-delete): DB unavailable raises, sets deleted_at/deleted_by, not a hard delete
  - purge_workspace: blocked by live documents, blocked by live conversations, hard-deletes otherwise
  - add_workspace_member: DB unavailable raises, upserts
  - remove_workspace_member: DB unavailable raises, refuses to remove last owner, removes otherwise
  - get_workspace_owner: DB unavailable returns None, returns owner id
  - get_workspace_member_role: DB unavailable returns None, returns role
  - list_workspace_members: DB unavailable returns [], returns list of dicts
  - get_user_workspaces: DB unavailable returns [], returns list with role
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


def _workspaces_mixin(connected=True, **conn_kwargs):
    from src.db.workspaces import WorkspacesMixin

    conn, cur = _make_conn_ctx(**conn_kwargs)
    m = WorkspacesMixin()
    m.is_connected = connected
    m.get_connection = MagicMock(return_value=conn)
    return m, conn, cur


# ===========================================================================
# create_workspace
# ===========================================================================

class TestCreateWorkspace:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _workspaces_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.create_workspace("My Workspace")

    def test_returns_string_id(self):
        wid = uuid.uuid4()
        m, _, cur = _workspaces_mixin(fetchone_return=(wid,))
        result = m.create_workspace("My Workspace")
        assert result == str(wid)

    def test_truncates_long_name(self):
        m, _, cur = _workspaces_mixin(fetchone_return=(uuid.uuid4(),))
        long_name = "x" * 300
        m.create_workspace(long_name)
        params = cur.execute.call_args[0][1]
        assert len(params[0]) == 255

    def test_passes_description_prompt_and_model_class(self):
        m, _, cur = _workspaces_mixin(fetchone_return=(uuid.uuid4(),))
        m.create_workspace("WS", description="desc", system_prompt="prompt", model_class="FAST")
        params = cur.execute.call_args[0][1]
        assert params == ("WS", "desc", "prompt", "FAST")


# ===========================================================================
# get_workspace
# ===========================================================================

class TestGetWorkspace:
    def test_returns_none_when_db_unavailable(self):
        m, _, _ = _workspaces_mixin(connected=False)
        assert m.get_workspace("some-id") is None

    def test_returns_none_when_not_found(self):
        m, _, _ = _workspaces_mixin(fetchone_return=None)
        assert m.get_workspace("missing-id") is None

    def test_returns_workspace_dict_when_found(self):
        from datetime import datetime
        wid = uuid.uuid4()
        m, _, cur = _workspaces_mixin(
            fetchone_return=(wid, "Default", "desc", "prompt", "FAST", datetime(2025, 1, 1))
        )
        result = m.get_workspace(str(wid))
        assert result["id"] == str(wid)
        assert result["name"] == "Default"
        assert result["model_class"] == "FAST"

    def test_query_filters_soft_deleted_rows(self):
        m, _, cur = _workspaces_mixin(fetchone_return=None)
        m.get_workspace("some-id")
        query = cur.execute.call_args[0][0]
        assert "deleted_at IS NULL" in query


# ===========================================================================
# list_workspaces
# ===========================================================================

class TestListWorkspaces:
    def test_returns_empty_when_db_unavailable(self):
        m, _, _ = _workspaces_mixin(connected=False)
        assert m.list_workspaces() == []

    def test_returns_workspace_dicts_with_counts(self):
        from datetime import datetime
        wid = uuid.uuid4()
        m, _, cur = _workspaces_mixin(
            fetchall_return=[(wid, "Default", "desc", "prompt", "FAST", datetime(2025, 1, 1), 3, 5)]
        )
        result = m.list_workspaces()
        assert len(result) == 1
        assert result[0]["document_count"] == 3
        assert result[0]["conversation_count"] == 5

    def test_query_filters_soft_deleted_workspaces(self):
        m, _, cur = _workspaces_mixin(fetchall_return=[])
        m.list_workspaces()
        query = cur.execute.call_args[0][0]
        assert "w.deleted_at IS NULL" in query


# ===========================================================================
# get_default_workspace_id
# ===========================================================================

class TestGetDefaultWorkspaceId:
    def test_returns_none_when_db_unavailable(self):
        m, _, _ = _workspaces_mixin(connected=False)
        assert m.get_default_workspace_id() is None

    def test_returns_none_when_no_workspace_exists(self):
        m, _, _ = _workspaces_mixin(fetchone_return=None)
        assert m.get_default_workspace_id() is None

    def test_returns_id_of_oldest_workspace(self):
        wid = uuid.uuid4()
        m, _, cur = _workspaces_mixin(fetchone_return=(wid,))
        assert m.get_default_workspace_id() == str(wid)


# ===========================================================================
# update_workspace
# ===========================================================================

class TestUpdateWorkspace:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _workspaces_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.update_workspace("wid", name="New")

    def test_returns_false_when_no_fields_given(self):
        m, _, cur = _workspaces_mixin()
        result = m.update_workspace("wid")
        assert result is False
        m.get_connection.assert_not_called()

    def test_updates_only_provided_fields(self):
        m, _, cur = _workspaces_mixin(rowcount=1)
        m.update_workspace("wid", name="New Name")
        query = cur.execute.call_args[0][0]
        assert "name = %s" in query
        assert "description = %s" not in query

    def test_truncates_long_name(self):
        m, _, cur = _workspaces_mixin(rowcount=1)
        m.update_workspace("wid", name="x" * 300)
        params = cur.execute.call_args[0][1]
        assert len(params[0]) == 255

    def test_updates_system_prompt_and_model_class(self):
        m, _, cur = _workspaces_mixin(rowcount=1)
        m.update_workspace("wid", system_prompt="be helpful", model_class="LARGE")
        query = cur.execute.call_args[0][0]
        params = cur.execute.call_args[0][1]
        assert "system_prompt = %s" in query
        assert "model_class = %s" in query
        assert params == ["be helpful", "LARGE", "wid"]

    def test_returns_true_when_row_updated(self):
        m, _, cur = _workspaces_mixin(rowcount=1)
        assert m.update_workspace("wid", description="new desc") is True

    def test_returns_false_when_no_row_matched(self):
        m, _, cur = _workspaces_mixin(rowcount=0)
        assert m.update_workspace("wid", description="new desc") is False


# ===========================================================================
# delete_workspace (soft-delete) / purge_workspace (hard delete)
# ===========================================================================

class TestDeleteWorkspace:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _workspaces_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.delete_workspace("wid")

    def test_sets_deleted_at_and_deleted_by_not_hard_delete(self):
        m, _, cur = _workspaces_mixin(rowcount=1)
        m.delete_workspace("wid", deleted_by="admin-id")
        query = cur.execute.call_args[0][0]
        assert "UPDATE workspaces SET deleted_at" in query
        assert "DELETE FROM" not in query
        params = cur.execute.call_args[0][1]
        assert params == ("admin-id", "wid")

    def test_returns_true_when_row_retired(self):
        m, _, cur = _workspaces_mixin(rowcount=1)
        assert m.delete_workspace("wid") is True

    def test_returns_false_when_already_deleted(self):
        m, _, cur = _workspaces_mixin(rowcount=0)
        assert m.delete_workspace("wid") is False


class TestPurgeWorkspace:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _workspaces_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.purge_workspace("wid")

    def test_blocked_when_live_documents_exist(self):
        m, _, cur = _workspaces_mixin(fetchone_return=(1,))
        result = m.purge_workspace("wid")
        assert result is False
        assert cur.execute.call_count == 1

    def test_blocked_when_live_conversations_exist(self):
        m, _, cur = _workspaces_mixin()
        cur.fetchone.side_effect = [None, (1,)]  # no docs, but a live conversation
        result = m.purge_workspace("wid")
        assert result is False
        assert cur.execute.call_count == 2

    def test_hard_deletes_when_no_live_references(self):
        m, _, cur = _workspaces_mixin()
        cur.fetchone.side_effect = [None, None]
        cur.rowcount = 1
        result = m.purge_workspace("wid")
        assert result is True
        delete_query = cur.execute.call_args_list[-1][0][0]
        assert "DELETE FROM workspaces" in delete_query


# ===========================================================================
# Membership
# ===========================================================================

class TestAddWorkspaceMember:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _workspaces_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.add_workspace_member("wid", "uid")

    def test_upserts_member_role(self):
        m, _, cur = _workspaces_mixin()
        m.add_workspace_member("wid", "uid", role="editor")
        query = cur.execute.call_args[0][0]
        assert "ON CONFLICT" in query
        params = cur.execute.call_args[0][1]
        assert params == ("wid", "uid", "editor")


class TestRemoveWorkspaceMember:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _workspaces_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.remove_workspace_member("wid", "uid")

    def test_removes_non_owner_member(self):
        m, _, cur = _workspaces_mixin(rowcount=1)
        cur.fetchone.return_value = ("viewer",)
        result = m.remove_workspace_member("wid", "uid")
        assert result is True

    def test_raises_when_removing_last_owner(self):
        m, _, cur = _workspaces_mixin()
        cur.fetchone.side_effect = [("owner",), (1,)]
        with pytest.raises(ValueError, match="last owner"):
            m.remove_workspace_member("wid", "uid")

    def test_allows_removing_owner_when_other_owners_exist(self):
        m, _, cur = _workspaces_mixin(rowcount=1)
        cur.fetchone.side_effect = [("owner",), (2,)]
        result = m.remove_workspace_member("wid", "uid")
        assert result is True

    def test_returns_false_when_no_row_removed(self):
        m, _, cur = _workspaces_mixin(rowcount=0)
        cur.fetchone.return_value = ("viewer",)
        assert m.remove_workspace_member("wid", "uid") is False


class TestGetWorkspaceOwner:
    def test_returns_none_when_db_unavailable(self):
        m, _, _ = _workspaces_mixin(connected=False)
        assert m.get_workspace_owner("wid") is None

    def test_returns_none_when_no_owner(self):
        m, _, _ = _workspaces_mixin(fetchone_return=None)
        assert m.get_workspace_owner("wid") is None

    def test_returns_owner_user_id(self):
        uid = uuid.uuid4()
        m, _, cur = _workspaces_mixin(fetchone_return=(uid,))
        assert m.get_workspace_owner("wid") == str(uid)


class TestGetWorkspaceMemberRole:
    def test_returns_none_when_db_unavailable(self):
        m, _, _ = _workspaces_mixin(connected=False)
        assert m.get_workspace_member_role("wid", "uid") is None

    def test_returns_none_when_not_a_member(self):
        m, _, _ = _workspaces_mixin(fetchone_return=None)
        assert m.get_workspace_member_role("wid", "uid") is None

    def test_returns_role_when_member(self):
        m, _, cur = _workspaces_mixin(fetchone_return=("editor",))
        assert m.get_workspace_member_role("wid", "uid") == "editor"


class TestListWorkspaceMembers:
    def test_returns_empty_when_db_unavailable(self):
        m, _, _ = _workspaces_mixin(connected=False)
        assert m.list_workspace_members("wid") == []

    def test_returns_member_dicts(self):
        from datetime import datetime
        uid = uuid.uuid4()
        m, _, cur = _workspaces_mixin(
            fetchall_return=[(uid, "alice", "a@example.com", "owner", datetime(2025, 1, 1))]
        )
        result = m.list_workspace_members("wid")
        assert len(result) == 1
        assert result[0]["username"] == "alice"
        assert result[0]["role"] == "owner"


class TestGetUserWorkspaces:
    def test_returns_empty_when_db_unavailable(self):
        m, _, _ = _workspaces_mixin(connected=False)
        assert m.get_user_workspaces("uid") == []

    def test_returns_workspace_dicts_with_role(self):
        from datetime import datetime
        wid = uuid.uuid4()
        m, _, cur = _workspaces_mixin(
            fetchall_return=[(wid, "Default", "desc", "prompt", "FAST", datetime(2025, 1, 1), "owner")]
        )
        result = m.get_user_workspaces("uid")
        assert len(result) == 1
        assert result[0]["role"] == "owner"
        assert result[0]["name"] == "Default"
