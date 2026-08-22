"""
Users Mixin
===========

Provides CRUD operations for the ``users`` table.
Passwords are hashed with Werkzeug's PBKDF2-SHA256 (stored hash includes salt).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from werkzeug.security import check_password_hash, generate_password_hash

from ..utils.logging_config import get_logger, sanitize_log_value
from .connection import DatabaseUnavailableError

if TYPE_CHECKING:
    from .connection import MixinHost
else:
    MixinHost = object

logger = get_logger(__name__)


class LastAdminError(Exception):
    """Raised when an operation would leave the installation with no live admin.

    A precondition in the Clark-Wilson sense: the transformation is refused rather
    than allowed to produce a state no integrity check could repair — there would be
    nobody able to grant the role back.
    """


class UsersMixin(MixinHost):
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
                row = cur.fetchone()
                assert row is not None, "INSERT ... RETURNING id always returns a row"
                user_id = str(row[0])
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
                    FROM users WHERE username = %s AND deleted_at IS NULL
                    """,
                    (username.lower().strip(),),
                )
                row = cur.fetchone()
        return _row_to_user(row) if row else None

    def get_user_role(self, user_id: str) -> str | None:
        """Return the user's current global role, or None if there is no live user.

        Narrower than get_user_by_id on purpose: the authorisation guard runs this on
        every admin request and has no business loading the password hash to do it.
        Filters deleted_at, so a retired administrator resolves to None.
        """
        if not self.is_connected:
            return None
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT role FROM users WHERE id = %s AND deleted_at IS NULL",
                    (user_id,),
                )
                row = cur.fetchone()
                return row[0] if row else None

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        """Return user dict or None."""
        if not self.is_connected:
            return None
        with self.get_connection() as conn:
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

    def list_users(self, include_retired: bool = False) -> list[dict[str, Any]]:
        """Return users, hashed_password excluded.

        *include_retired* also returns soft-deleted rows so a management screen can
        show them distinctly rather than hiding them — a retired user is still
        referenced by their documents and conversations, so a list that omits them
        disagrees with the data.
        """
        if not self.is_connected:
            return []
        with self.get_connection() as conn:
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

    def count_users(self) -> int:
        """Return count of live (non-deleted) users."""
        if not self.is_connected:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users WHERE deleted_at IS NULL")
                row = cur.fetchone()
                assert row is not None, "SELECT COUNT(*) always returns a row"
                return row[0]

    def count_live_admins(self) -> int:
        """Number of live users holding the global admin role."""
        if not self.is_connected:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND deleted_at IS NULL"
                )
                row = cur.fetchone()
                assert row is not None, "SELECT COUNT(*) always returns a row"
                return row[0]

    def _would_remove_last_admin(self, user_id: str) -> bool:
        """True when this user is the only remaining live admin.

        Enforced here rather than in the UI: a greyed-out button is a courtesy, not
        a precondition. Without this the API happily leaves an installation with no
        one able to manage users, models or settings — recoverable only by editing
        the database directly.
        """
        user = self.get_user_by_id(user_id)
        if not user or user.get("role") != "admin":
            return False
        return self.count_live_admins() <= 1

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
        # Demoting or deactivating the last admin locks everyone out of user,
        # model and settings management.
        demotes = fields.get('role') not in (None, 'admin')
        deactivates = fields.get('is_active') is False
        if (demotes or deactivates) and self._would_remove_last_admin(user_id):
            raise LastAdminError("Cannot remove the last remaining admin")
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

    def delete_user(self, user_id: str, deleted_by: str | None = None) -> bool:
        """Soft-delete a user. Returns True if a live row was retired."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot delete user: DB not connected")
        if self._would_remove_last_admin(user_id):
            raise LastAdminError("Cannot delete the last remaining admin")
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET deleted_at = NOW(), deleted_by = %s WHERE id = %s AND deleted_at IS NULL",
                    (deleted_by, user_id),
                )
                return cur.rowcount > 0

    def purge_user(self, user_id: str) -> bool:
        """Hard-delete a soft-deleted user if no workspace memberships exist. Returns False when blocked."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot purge user: DB not connected")
        with self.get_connection() as conn:
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
        return deleted

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
    """Map a users row positionally.

    ``deleted_at`` is optional because only list_users(include_retired=True)
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
