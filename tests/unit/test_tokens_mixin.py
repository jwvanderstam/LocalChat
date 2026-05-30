"""Unit tests for TokensMixin (JWT revocation deny-list)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.db.tokens import TokensMixin


class _FakeDB(TokensMixin):
    """Minimal stand-in that satisfies get_connection via a mock."""

    def __init__(self, cursor_rows=None, rowcount=0):
        self._rows = cursor_rows or []
        self._rowcount = rowcount

    def get_connection(self):
        from contextlib import contextmanager

        cur = MagicMock()
        cur.fetchone.return_value = self._rows[0] if self._rows else None
        cur.rowcount = self._rowcount
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = lambda s: cur
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        @contextmanager
        def _ctx():
            yield conn

        return _ctx()


@pytest.mark.unit
class TestRevokToken:

    def test_revoke_executes_insert(self):
        db = _FakeDB()
        jti = str(uuid.uuid4())
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        with patch.object(db, "get_connection", wraps=db.get_connection) as mock_gc:
            db.revoke_token(jti, expires_at)
        mock_gc.assert_called_once()

    def test_revoke_accepts_past_expiry(self):
        db = _FakeDB()
        jti = str(uuid.uuid4())
        past = datetime.now(UTC) - timedelta(seconds=1)
        db.revoke_token(jti, past)  # should not raise


@pytest.mark.unit
class TestIsTokenRevoked:

    def test_returns_true_when_row_found(self):
        db = _FakeDB(cursor_rows=[(1,)])
        assert db.is_token_revoked("some-jti") is True

    def test_returns_false_when_no_row(self):
        db = _FakeDB(cursor_rows=[])
        assert db.is_token_revoked("some-jti") is False


@pytest.mark.unit
class TestPurgeExpiredTokens:

    def test_returns_rowcount(self):
        db = _FakeDB(rowcount=3)
        result = db.purge_expired_tokens()
        assert result == 3

    def test_returns_zero_when_nothing_deleted(self):
        db = _FakeDB(rowcount=0)
        assert db.purge_expired_tokens() == 0
