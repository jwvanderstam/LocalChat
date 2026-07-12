"""
OAuth Tokens Mixin
==================

Stores and retrieves encrypted OAuth2 access/refresh tokens for third-party
providers.  Encryption is delegated to ``src/utils/encryption.py`` so the
same Fernet key covers all sensitive columns.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..utils.encryption import decrypt as _decrypt
from ..utils.encryption import encrypt as _encrypt
from ..utils.logging_config import get_logger
from .connection import DatabaseUnavailableError

if TYPE_CHECKING:
    from .connection import MixinHost
else:
    MixinHost = object

logger = get_logger(__name__)


class OAuthTokensMixin(MixinHost):
    """Mixin providing OAuth token storage with optional encryption."""

    def upsert_oauth_token(
        self,
        user_id: str,
        provider: str,
        access_token: str,
        refresh_token: str | None = None,
        expires_at: datetime | None = None,
        scopes: list[str] | None = None,
    ) -> None:
        """Store or update an OAuth token for (user_id, provider)."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot store token: DB not connected")
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO oauth_tokens
                        (user_id, provider, access_token, refresh_token, expires_at, scopes, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (user_id, provider) DO UPDATE SET
                        access_token  = EXCLUDED.access_token,
                        refresh_token = EXCLUDED.refresh_token,
                        expires_at    = EXCLUDED.expires_at,
                        scopes        = EXCLUDED.scopes,
                        updated_at    = NOW()
                    """,
                    (
                        user_id,
                        provider,
                        _encrypt(access_token),
                        _encrypt(refresh_token),
                        expires_at,
                        scopes or [],
                    ),
                )

    def get_oauth_token(self, user_id: str, provider: str) -> dict[str, Any] | None:
        """Return decrypted token dict or None."""
        if not self.is_connected:
            return None
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, user_id, provider, access_token, refresh_token,
                           expires_at, scopes, updated_at
                    FROM oauth_tokens
                    WHERE user_id = %s AND provider = %s
                    """,
                    (user_id, provider),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {
            'id': str(row[0]),
            'user_id': str(row[1]),
            'provider': row[2],
            'access_token': _decrypt(row[3]),
            'refresh_token': _decrypt(row[4]),
            'expires_at': row[5].isoformat() if row[5] else None,
            'scopes': row[6] or [],
            'updated_at': row[7].isoformat() if row[7] else None,
        }

    def is_token_expired(self, user_id: str, provider: str) -> bool:
        """Return True if the stored token has expired (or doesn't exist)."""
        token = self.get_oauth_token(user_id, provider)
        if not token:
            return True
        expires_at_str = token.get('expires_at')
        if not expires_at_str:
            return False  # No expiry set — assume valid
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            return datetime.now(UTC) >= expires_at
        except Exception:
            return True

    def delete_oauth_token(self, user_id: str, provider: str) -> bool:
        """Remove the token for (user_id, provider). Returns True if deleted."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete token: DB not connected")
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM oauth_tokens WHERE user_id = %s AND provider = %s",
                    (user_id, provider),
                )
                return cur.rowcount > 0
