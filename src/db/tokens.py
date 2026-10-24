"""Revoked-tokens repository — the JWT deny-list backed by PostgreSQL."""

from __future__ import annotations

from datetime import datetime

from .connection import DatabaseConnection


class RevokedTokensRepository:
    """The ``revoked_tokens`` table: one row per signed-out token, until it expires."""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    def revoke(self, jti: str, expires_at: datetime) -> None:
        """Insert a token's jti into the deny-list."""
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO revoked_tokens (jti, expires_at) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (jti, expires_at),
                )

    def is_revoked(self, jti: str) -> bool:
        """Return True when the jti is in the deny-list."""
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM revoked_tokens WHERE jti = %s", (jti,))
                return cur.fetchone() is not None

    def purge_expired(self) -> int:
        """Delete deny-list rows whose token has already expired. Returns row count."""
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM revoked_tokens WHERE expires_at < NOW()")
                return int(cur.rowcount)
