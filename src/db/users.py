"""Users repository — the SQL for the ``users`` table, and nothing else.

Who may change a user, the last-administrator rule and password checking are
decisions, so they live in ``src/services/users.py`` (ADR-7).
"""
from __future__ import annotations

from typing import Any

from ..utils.logging_config import get_logger, sanitize_log_value
from ..utils.scope import ALL_WORKSPACES
from .connection import DatabaseConnection, DatabaseUnavailableError

logger = get_logger(__name__)

#: The columns ``update`` may set. A fixed list, because the SET clause is built from it.
_UPDATABLE = frozenset({'email', 'hashed_password', 'is_active', 'role'})


class UsersRepository:
    """User rows: create, read, update, retire and purge."""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    def create(
        self,
        username: str,
        hashed_password: str,
        email: str | None = None,
        role: str = 'user',
    ) -> str:
        """Insert a user row and return its UUID string."""
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot create user: DB not connected")
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (username, email, hashed_password, role)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (username.lower().strip(), email, hashed_password, role),
                )
                row = cur.fetchone()
                if row is None:
                    raise AssertionError("INSERT ... RETURNING id always returns a row")
                user_id = str(row[0])
        logger.info(f"[Users] Created user '{username}' id={user_id}")
        return user_id

    def seed_admin(self, username: str, hashed_password: str, role: str = 'admin') -> None:
        """Insert the admin user if no row with that username exists yet.

        Uses INSERT ... ON CONFLICT DO NOTHING so concurrent workers calling
        this at startup are safe without any application-level locking.
        """
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot seed admin user: DB not connected")
        with self._db.get_connection() as conn:
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

    def get_by_username(self, username: str) -> dict[str, Any] | None:
        """Return the live user, hash included, or None."""
        if not self._db.is_connected:
            return None
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, email, hashed_password, is_active, role, created_at
                    FROM users WHERE username = %s AND deleted_at IS NULL
                    """,
                    (username.lower().strip(),),
                )
                row = cur.fetchone()
        return _row_to_user(row) if row else None

    def get_role(self, user_id: str) -> str | None:
        """Return the user's current global role, or None if there is no live, active user.

        Narrower than get_by_id on purpose: the authorisation guard runs this on
        every admin request and has no business loading the password hash to do it.
        Filters deleted_at and is_active, so a retired or deactivated administrator
        resolves to None; is_active used to be read at login only (R-4).
        """
        if not self._db.is_connected:
            return None
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT role FROM users WHERE id = %s AND deleted_at IS NULL AND is_active",
                    (user_id,),
                )
                row = cur.fetchone()
                return str(row[0]) if row else None

    def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        """Return the live user, hash included, or None."""
        if not self._db.is_connected:
            return None
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, email, hashed_password, is_active, role, created_at
                    FROM users WHERE id = %s AND deleted_at IS NULL
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
        return _row_to_user(row) if row else None

    def list_all(self, include_retired: bool = False) -> list[dict[str, Any]]:
        """Return users, oldest first.

        *include_retired* also returns soft-deleted rows so a management screen can
        show them distinctly rather than hiding them — a retired user is still
        referenced by their documents and conversations, so a list that omits them
        disagrees with the data.
        """
        if not self._db.is_connected:
            return []
        with self._db.get_connection(scope=ALL_WORKSPACES) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, email, hashed_password, is_active, role,
                           created_at, deleted_at
                    FROM users
                    WHERE (deleted_at IS NULL OR %s)
                    ORDER BY created_at
                    """,
                    (include_retired,),
                )
                rows = cur.fetchall()
        return [_row_to_user(r) for r in rows]

    def count(self) -> int:
        """Return count of live (non-deleted) users."""
        if not self._db.is_connected:
            return 0
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users WHERE deleted_at IS NULL")
                row = cur.fetchone()
                if row is None:
                    raise AssertionError("SELECT COUNT(*) always returns a row")
                return int(row[0])

    def count_live_admins(self) -> int:
        """Number of live users holding the global admin role."""
        if not self._db.is_connected:
            return 0
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND deleted_at IS NULL"
                )
                row = cur.fetchone()
                if row is None:
                    raise AssertionError("SELECT COUNT(*) always returns a row")
                return int(row[0])

    def update(self, user_id: str, **fields: Any) -> bool:
        """Set the given columns. Returns True if a row was changed.

        Allowed keys: email, hashed_password, is_active, role; others are ignored.
        """
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot update user: DB not connected")
        sets = [f"{k} = %s" for k in fields if k in _UPDATABLE]
        params = [v for k, v in fields.items() if k in _UPDATABLE]
        if not sets:
            return False
        params.append(user_id)
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE users SET {', '.join(sets)} WHERE id = %s",  # nosec B608  # SET list from a fixed column whitelist; values are %s
                    params,
                )
                return bool(cur.rowcount > 0)

    def retire(self, user_id: str, deleted_by: str | None = None) -> bool:
        """Soft-delete a user. Returns True if a live row was retired."""
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot delete user: DB not connected")
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET deleted_at = NOW(), deleted_by = %s WHERE id = %s AND deleted_at IS NULL",
                    (deleted_by, user_id),
                )
                return bool(cur.rowcount > 0)

    def purge(self, user_id: str) -> bool:
        """Hard-delete a user if no workspace memberships exist. Returns False when blocked."""
        if not self._db.is_connected:
            raise DatabaseUnavailableError("Cannot purge user: DB not connected")
        with self._db.get_connection(scope=ALL_WORKSPACES) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM workspace_members WHERE user_id = %s LIMIT 1",
                    (user_id,),
                )
                if cur.fetchone():
                    logger.debug("Purge blocked: user %s has workspace memberships",
                                 sanitize_log_value(user_id))
                    return False
                cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
                deleted = cur.rowcount > 0
        if deleted:
            logger.info("Purged user: %s", sanitize_log_value(user_id))
        return bool(deleted)


def _row_to_user(row: tuple[Any, ...]) -> dict[str, Any]:
    """Map a users row positionally.

    ``deleted_at`` is optional because only list_all(include_retired=True)
    selects it; the single-row lookups filter retired users out entirely, so an
    eighth column would always be NULL there. Reading it defensively keeps this
    mapper usable from both without a second function — and silently dropping a
    selected column is how the retired badge first failed to appear.
    """
    user = {
        'id': str(row[0]),
        'username': row[1],
        'email': row[2],
        'hashed_password': row[3],   # caller strips this before returning to API
        'is_active': row[4],
        'role': row[5],
        'created_at': row[6].isoformat() if row[6] else None,
    }
    if len(row) > 7:
        user['deleted_at'] = row[7].isoformat() if row[7] else None
    return user
