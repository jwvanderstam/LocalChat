"""
Tests for src/db/oauth_tokens.py (OAuthTokensRepository)

Covers:
  - upsert_oauth_token: DB unavailable raises, encrypts access/refresh tokens before storing,
    upserts on (user_id, provider) conflict
  - get_oauth_token: DB unavailable returns None, not found returns None, decrypts tokens,
    round-trips through real Fernet encryption when ENCRYPTION_KEY is configured
  - is_token_expired: no token found, no expiry set, expired, not expired, malformed expiry
  - delete_oauth_token: DB unavailable raises, returns bool
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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


class _Host:
    """The connection a repository runs over, holding it as ``Database`` does."""


def _oauth_mixin(connected=True, **conn_kwargs):
    from src.db.oauth_tokens import OAuthTokensRepository

    conn, cur = _make_conn_ctx(**conn_kwargs)
    m = _Host()
    m.is_connected = connected
    m.get_connection = MagicMock(return_value=conn)
    m.oauth_tokens = OAuthTokensRepository(m)
    return m, conn, cur


# ===========================================================================
# upsert_oauth_token
# ===========================================================================

class TestUpsertOauthToken:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _oauth_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.oauth_tokens.upsert("uid", "google", "access-token")

    def test_upserts_on_conflict(self):
        m, _, cur = _oauth_mixin()
        m.oauth_tokens.upsert("uid", "google", "access-token")
        query = cur.execute.call_args[0][0]
        assert "ON CONFLICT (user_id, provider) DO UPDATE" in query

    def test_stores_encrypted_access_token_not_plaintext(self, monkeypatch):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        monkeypatch.setattr("src.config.ENCRYPTION_KEY", key)
        m, _, cur = _oauth_mixin()
        m.oauth_tokens.upsert("uid", "google", "super-secret-access-token")
        params = cur.execute.call_args[0][1]
        stored_access_token = params[2]
        assert stored_access_token != "super-secret-access-token"
        assert Fernet(key.encode()).decrypt(stored_access_token.encode()).decode() == "super-secret-access-token"

    def test_passes_empty_list_when_scopes_omitted(self):
        m, _, cur = _oauth_mixin()
        m.oauth_tokens.upsert("uid", "google", "access-token")
        params = cur.execute.call_args[0][1]
        assert params[5] == []

    def test_passes_provided_scopes(self):
        m, _, cur = _oauth_mixin()
        m.oauth_tokens.upsert("uid", "google", "access-token", scopes=["email", "profile"])
        params = cur.execute.call_args[0][1]
        assert params[5] == ["email", "profile"]


# ===========================================================================
# get_oauth_token
# ===========================================================================

class TestGetOauthToken:
    def test_returns_none_when_db_unavailable(self):
        m, _, _ = _oauth_mixin(connected=False)
        assert m.oauth_tokens.get("uid", "google") is None

    def test_returns_none_when_not_found(self):
        m, _, _ = _oauth_mixin(fetchone_return=None)
        assert m.oauth_tokens.get("uid", "google") is None

    def test_returns_decrypted_token_dict(self):
        import uuid
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        m, _, cur = _oauth_mixin(
            fetchone_return=(
                tid, uid, "google", "plaintext-access", "plaintext-refresh",
                datetime(2025, 1, 1), ["email"], datetime(2025, 1, 1),
            )
        )
        result = m.oauth_tokens.get(str(uid), "google")
        # No ENCRYPTION_KEY configured in the default test env -> decrypt() is a pass-through.
        assert result["access_token"] == "plaintext-access"
        assert result["refresh_token"] == "plaintext-refresh"
        assert result["provider"] == "google"
        assert result["scopes"] == ["email"]

    def test_round_trips_through_real_encryption(self, monkeypatch):
        import uuid

        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        monkeypatch.setattr("src.config.ENCRYPTION_KEY", key)
        fernet = Fernet(key.encode())
        encrypted_access = fernet.encrypt(b"my-access-token").decode()
        encrypted_refresh = fernet.encrypt(b"my-refresh-token").decode()

        tid = uuid.uuid4()
        uid = uuid.uuid4()
        m, _, cur = _oauth_mixin(
            fetchone_return=(
                tid, uid, "microsoft", encrypted_access, encrypted_refresh,
                None, None, None,
            )
        )
        result = m.oauth_tokens.get(str(uid), "microsoft")
        assert result["access_token"] == "my-access-token"
        assert result["refresh_token"] == "my-refresh-token"
        assert result["scopes"] == []

    def test_handles_missing_optional_fields(self):
        import uuid
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        m, _, cur = _oauth_mixin(
            fetchone_return=(tid, uid, "google", "access", None, None, None, None)
        )
        result = m.oauth_tokens.get(str(uid), "google")
        assert result["refresh_token"] is None
        assert result["expires_at"] is None
        assert result["scopes"] == []


# ===========================================================================
# is_token_expired
# ===========================================================================

class TestIsTokenExpired:
    def test_returns_true_when_no_token_found(self):
        m, _, _ = _oauth_mixin(fetchone_return=None)
        assert m.oauth_tokens.is_expired("uid", "google") is True

    def test_returns_false_when_no_expiry_set(self):
        import uuid
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        m, _, cur = _oauth_mixin(
            fetchone_return=(tid, uid, "google", "access", None, None, None, None)
        )
        assert m.oauth_tokens.is_expired(str(uid), "google") is False

    def test_returns_true_when_expiry_in_the_past(self):
        import uuid
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        past = datetime.now(UTC) - timedelta(hours=1)
        m, _, cur = _oauth_mixin(
            fetchone_return=(tid, uid, "google", "access", None, past, None, None)
        )
        assert m.oauth_tokens.is_expired(str(uid), "google") is True

    def test_returns_false_when_expiry_in_the_future(self):
        import uuid
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        future = datetime.now(UTC) + timedelta(hours=1)
        m, _, cur = _oauth_mixin(
            fetchone_return=(tid, uid, "google", "access", None, future, None, None)
        )
        assert m.oauth_tokens.is_expired(str(uid), "google") is False

    def test_returns_true_on_malformed_expiry(self):
        m, _, _ = _oauth_mixin()
        m.oauth_tokens.get = MagicMock(return_value={"expires_at": "not-a-date"})
        assert m.oauth_tokens.is_expired("uid", "google") is True

    def test_treats_naive_expiry_as_utc(self):
        import uuid
        tid = uuid.uuid4()
        uid = uuid.uuid4()
        naive_past = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        m, _, cur = _oauth_mixin(
            fetchone_return=(tid, uid, "google", "access", None, naive_past, None, None)
        )
        assert m.oauth_tokens.is_expired(str(uid), "google") is True


# ===========================================================================
# delete_oauth_token
# ===========================================================================

class TestDeleteOauthToken:
    def test_raises_when_db_unavailable(self):
        from src.db.connection import DatabaseUnavailableError
        m, _, _ = _oauth_mixin(connected=False)
        with pytest.raises(DatabaseUnavailableError):
            m.oauth_tokens.delete("uid", "google")

    def test_returns_true_when_row_deleted(self):
        m, _, cur = _oauth_mixin(rowcount=1)
        assert m.oauth_tokens.delete("uid", "google") is True

    def test_returns_false_when_no_row_matched(self):
        m, _, cur = _oauth_mixin(rowcount=0)
        assert m.oauth_tokens.delete("uid", "google") is False
