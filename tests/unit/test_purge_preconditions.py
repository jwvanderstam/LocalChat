"""The purge transformation procedures — Clark-Wilson's irreversible half.

`CLAUDE.md` separates "Retire" (soft-delete, reversible) from "Destroy" (purge,
irreversible, authorised). A purge is only permitted when no live data still
holds the id, so the precondition query *is* the safety property — if it stops
blocking, a conversation gets destroyed while memories still cite it.

Neither purge had a unit test. The route-level tests in `test_cw2_soft_delete.py`
mock these methods out entirely, so nothing exercised the precondition itself.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.db.connection import DatabaseUnavailableError
from src.db.conversations import ConversationsRepository
from src.db.users import UsersRepository

pytestmark = pytest.mark.unit

CONV = "11111111-1111-1111-1111-111111111111"
USER = "22222222-2222-2222-2222-222222222222"


def _mixin(cls, *, cites: bool, rowcount: int = 1, connected: bool = True):
    """A mixin whose first SELECT answers "something still references this" or not."""
    cur = MagicMock()
    cur.fetchone.return_value = (1,) if cites else None
    cur.rowcount = rowcount
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    m = cls()
    m.is_connected = connected
    m.get_connection = MagicMock(return_value=conn)
    return m, cur


class _Host:
    """What a repository needs from its connection: is_connected and get_connection."""


def _conversations(**kwargs):
    host, cur = _mixin(_Host, **kwargs)
    host.conversations = ConversationsRepository(host)
    return host, cur


def _users(**kwargs):
    host, cur = _mixin(_Host, **kwargs)
    return UsersRepository(host), cur


def _statements(cur) -> list[str]:
    return [call.args[0] for call in cur.execute.call_args_list]


class TestPurgeConversation:
    def test_a_cited_conversation_is_refused(self):
        m, _ = _conversations(cites=True)
        assert m.conversations.purge(CONV) is False

    def test_a_cited_conversation_is_not_deleted(self):
        """The refusal has to happen *before* the DELETE, not alongside it."""
        m, cur = _conversations(cites=True)
        m.conversations.purge(CONV)

        assert not any("DELETE" in sql for sql in _statements(cur))

    def test_an_uncited_conversation_is_deleted(self):
        m, cur = _conversations(cites=False)

        assert m.conversations.purge(CONV) is True
        assert any("DELETE FROM conversations" in sql for sql in _statements(cur))

    def test_deleting_nothing_reports_false(self):
        """No matching row is not a successful purge — a caller that reported
        success here would tell the user a record was destroyed that still exists."""
        m, _ = _conversations(cites=False, rowcount=0)
        assert m.conversations.purge(CONV) is False

    def test_no_database_refuses_rather_than_returning_false(self):
        """False means "blocked by a reference". An unreachable database is a
        different answer and must not be collapsed into it."""
        m, _ = _conversations(cites=False, connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.conversations.purge(CONV)


class TestPurgeUser:
    def test_a_user_with_memberships_is_refused(self):
        m, _ = _users(cites=True)
        assert m.purge(USER) is False

    def test_a_user_with_memberships_is_not_deleted(self):
        m, cur = _users(cites=True)
        m.purge(USER)

        assert not any("DELETE" in sql for sql in _statements(cur))

    def test_a_user_without_memberships_is_deleted(self):
        m, cur = _users(cites=False)

        assert m.purge(USER) is True
        assert any("DELETE FROM users" in sql for sql in _statements(cur))

    def test_no_database_refuses_rather_than_returning_false(self):
        m, _ = _users(cites=False, connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.purge(USER)

