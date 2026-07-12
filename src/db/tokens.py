"""Tokens Mixin — JWT revocation deny-list backed by PostgreSQL."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .connection import MixinHost
else:
    MixinHost = object


class TokensMixin(MixinHost):
    """Mixin that adds JWT revocation operations to the Database class."""

    def revoke_token(self, jti: str, expires_at: datetime) -> None:
        """Insert a token's jti into the deny-list."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO revoked_tokens (jti, expires_at) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (jti, expires_at),
                )

    def is_token_revoked(self, jti: str) -> bool:
        """Return True when the jti is in the deny-list."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM revoked_tokens WHERE jti = %s", (jti,))
                return cur.fetchone() is not None

    def purge_expired_tokens(self) -> int:
        """Delete deny-list rows whose token has already expired. Returns row count."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM revoked_tokens WHERE expires_at < NOW()")
                return cur.rowcount
