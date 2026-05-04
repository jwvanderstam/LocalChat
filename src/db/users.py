"""
Users Mixin
===========

Provides CRUD operations for the ``users`` table.
Passwords are hashed with Werkzeug's PBKDF2-SHA256 (stored hash includes salt).
"""
from __future__ import annotations

from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from ..utils.logging_config import get_logger
from .connection import DatabaseUnavailableError

logger = get_logger(__name__)


class UsersMixin:
    """Mixin providing user CRUD operations."""

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_user(
        self,
        username: str,
        hashed_password: str,
        email: str | None = None,
        role: str = 'user',
    ) -> str:
        """Insert a user row and return its UUID string.

        ``hashed_password`` must already be a Werkzeug hash string
        (use ``hash_user_password`` to produce one).
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot create user: DB not connected")
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (username, email, hashed_password, role)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (username.lower().strip(), email, hashed_password, role),
                )
                user_id = str(cur.fetchone()[0])
        logger.info(f"[Users] Created user '{username}' id={user_id}")
        return user_id

    def seed_admin_user(
        self,
        username: str,
        hashed_password: str,
        role: str = 'admin',
    ) -> None:
        """Insert the admin user if no row with that username exists yet.

        Uses INSERT ... ON CONFLICT DO NOTHING so concurrent workers calling
        this at startup are safe without any application-level locking.
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot seed admin user: DB not connected")
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (username, hashed_password, role)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (username) DO NOTHING
                    """,
                    (username.lower().strip(), hashed_password, role),
                )
                seeded = cur.rowcount == 1
        if seeded:
            logger.info(f"[Users] Admin user '{username}' seeded")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        """Return user dict (without hashed_password) or None."""
        if not self.is_connected:
            return None
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, email, hashed_password, is_active, role, created_at
                    FROM users WHERE username = %s
                    """,
                    (username.lower().strip(),),
                )
                row = cur.fetchone()
        return _row_to_user(row) if row else None

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        """Return user dict or None."""
        if not self.is_connected:
            return None
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, email, hashed_password, is_active, role, created_at
                    FROM users WHERE id = %s
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
        return _row_to_user(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        """Return all users (hashed_password excluded)."""
        if not self.is_connected:
            return []
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, email, hashed_password, is_active, role, created_at
                    FROM users ORDER BY created_at
                    """
                )
                rows = cur.fetchall()
        return [_row_to_user(r) for r in rows]

    def count_users(self) -> int:
        """Return total number of users."""
        if not self.is_connected:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users")
                return cur.fetchone()[0]

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_user(self, user_id: str, **fields) -> bool:
        """Update allowed user fields. Returns True if a row was changed.

        Allowed keys: email, hashed_password, is_active, role.
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot update user: DB not connected")
        allowed = {'email', 'hashed_password', 'is_active', 'role'}
        sets = [f"{k} = %s" for k in fields if k in allowed]
        params = [v for k, v in fields.items() if k in allowed]
        if not sets:
            return False
        params.append(user_id)
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE users SET {', '.join(sets)} WHERE id = %s",
                    params,
                )
                return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_user(self, user_id: str) -> bool:
        """Delete a user. Returns True if deleted."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete user: DB not connected")
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
                return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Password helpers
    # ------------------------------------------------------------------

    def verify_user_password(self, username: str, password: str) -> dict[str, Any] | None:
        """Return user dict if credentials are valid, else None."""
        user = self.get_user_by_username(username)
        if not user or not user.get('is_active'):
            return None
        stored_hash = user.pop('hashed_password', None)
        if stored_hash and check_password_hash(stored_hash, password):
            return user
        return None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def hash_user_password(password: str) -> str:
    """Return a Werkzeug PBKDF2-SHA256 hash string for ``password``."""
    return generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)


def _row_to_user(row: tuple) -> dict[str, Any]:
    return {
        'id': str(row[0]),
        'username': row[1],
        'email': row[2],
        'hashed_password': row[3],   # caller strips this before returning to API
        'is_active': row[4],
        'role': row[5],
        'created_at': row[6].isoformat() if row[6] else None,
    }
