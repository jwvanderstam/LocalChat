"""Workspace API keys — programmatic, non-human access to a single workspace.

A key is a principal in its own right, not a user wearing a service hat. It has no
password to reset and no session to expire; it is created, used, and revoked. That
keeps the audit trail honest: a chatbot bridge appears in the log as the key it is,
not as whichever person's account it borrowed.

Storage follows the same rule as passwords — the plaintext key is never stored. It
is returned exactly once, at creation.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from ..utils.logging_config import get_logger, sanitize_log_value
from .connection import DatabaseUnavailableError

if TYPE_CHECKING:
    from .connection import MixinHost
else:
    MixinHost = object

logger = get_logger(__name__)

#: Identifies our keys on sight, in a log or a pasted config, and lets a leaked
#: credential be traced back to this application rather than guessed at.
KEY_PREFIX = "lcw_"
_PREFIX_LEN = 12  # "lcw_" + 8 chars: enough to identify a key without revealing it


def generate_api_key() -> tuple[str, str, str]:
    """Return ``(full_key, prefix, key_hash)``. The full key is never stored."""
    secret = secrets.token_urlsafe(32)
    full = f"{KEY_PREFIX}{secret}"
    return full, full[:_PREFIX_LEN], _hash_key(full)


def _hash_key(key: str) -> str:
    """SHA-256, deliberately not PBKDF2.

    Password hashing is slow on purpose because passwords are low-entropy and
    guessable. An API key is 32 random bytes, so brute force is not the threat and a
    slow hash would only add latency to every single request. The stored value is
    still a hash, so a database leak does not yield usable credentials.
    """
    return hashlib.sha256(key.encode()).hexdigest()


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """Convert psycopg's UUID/datetime values to strings.

    These rows go straight into a JSONResponse, and json.dumps cannot serialise
    either type — a fault that only appears against a real database, since a mocked
    cursor hands back plain values.
    """
    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, UUID):
            out[key] = str(value)
        elif isinstance(value, datetime):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


class WorkspaceKeysMixin(MixinHost):
    """CRUD for workspace API keys."""

    def create_workspace_api_key(
        self,
        workspace_id: str,
        name: str,
        role: str = 'viewer',
        created_by: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Create a key and return ``(full_key, row)``.

        The caller must surface *full_key* once and never store it; only the hash
        and prefix are persisted.
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot create API key: DB not connected")
        full_key, prefix, key_hash = generate_api_key()
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workspace_api_keys
                        (workspace_id, name, key_prefix, key_hash, role, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, workspace_id, name, key_prefix, role, created_at
                    """,
                    (workspace_id, name.strip()[:120], prefix, key_hash, role, created_by),
                )
                row = cur.fetchone()
                assert row is not None, "INSERT ... RETURNING always returns a row"
                cols = [d[0] for d in cur.description or []]
        logger.info("[WorkspaceKeys] Key '%s' created for workspace %s",
                    prefix, sanitize_log_value(workspace_id))
        return full_key, _jsonable(dict(zip(cols, row, strict=True)))

    def resolve_workspace_api_key(self, presented: str) -> tuple[str, str] | None:
        """Return ``(workspace_id, role)`` for a live key, else ``None``.

        Looks up by prefix and then compares the hash in constant time, so the
        query plan does not depend on the secret and a timing signal does not leak
        how much of a guess was correct.
        """
        if not presented or not presented.startswith(KEY_PREFIX) or not self.is_connected:
            return None
        prefix = presented[:_PREFIX_LEN]
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, workspace_id, role, key_hash
                      FROM workspace_api_keys
                     WHERE key_prefix = %s AND revoked_at IS NULL
                    """,
                    (prefix,),
                )
                rows = cur.fetchall()
        expected = _hash_key(presented)
        for key_id, workspace_id, role, key_hash in rows:
            if hmac.compare_digest(key_hash, expected):
                self._touch_workspace_api_key(str(key_id))
                return str(workspace_id), role
        return None

    def _touch_workspace_api_key(self, key_id: str) -> None:
        """Record last use. Best-effort: a failure here must not deny a valid request."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE workspace_api_keys SET last_used_at = NOW() WHERE id = %s",
                        (key_id,),
                    )
        except Exception:
            logger.debug("[WorkspaceKeys] Could not record last_used_at for %s", key_id)

    def list_workspace_api_keys(self, workspace_id: str) -> list[dict[str, Any]]:
        """List live keys for a workspace. Never returns the key or its hash."""
        if not self.is_connected:
            return []
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, key_prefix, role, created_at, last_used_at
                      FROM workspace_api_keys
                     WHERE workspace_id = %s AND revoked_at IS NULL
                     ORDER BY created_at DESC
                    """,
                    (workspace_id,),
                )
                cols = [d[0] for d in cur.description or []]
                return [_jsonable(dict(zip(cols, r, strict=True))) for r in cur.fetchall()]

    def revoke_workspace_api_key(
        self,
        key_id: str,
        workspace_id: str,
        revoked_by: str | None = None,
    ) -> bool:
        """Revoke a key. Soft-delete per Clark-Wilson: the row stays for the audit trail.

        *workspace_id* is part of the WHERE clause, not just a lookup: without it an
        owner of one workspace could revoke another workspace's key by id.
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot revoke API key: DB not connected")
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE workspace_api_keys
                       SET revoked_at = NOW(), revoked_by = %s
                     WHERE id = %s AND workspace_id = %s AND revoked_at IS NULL
                    """,
                    (revoked_by, key_id, workspace_id),
                )
                return cur.rowcount > 0
