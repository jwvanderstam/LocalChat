"""Users and sessions: the use cases behind ``auth_routes`` (QP-4, ADR-7).

The routes parse and respond; this decides. Who may call the admin methods is still
the route's ``require_admin_dep`` — the users aggregate is not workspace-scoped, so
there is no ``Scope`` to check here. What lives here are the rules a guard cannot
express: the last administrator, the last owner of a workspace, and a password change
that must prove the current password.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..db.workspaces import LastOwnerError
from ..security_fastapi import verify_credentials_db
from ..utils.logging_config import get_logger
from .errors import ServiceError
from .passwords import hash_user_password, verify_user_password

if TYPE_CHECKING:
    from ..db import Database

logger = get_logger(__name__)

#: Matches the wording the workspaces router returns for the same refusal.
_LAST_OWNER = "Cannot remove the last owner of a workspace"


class LastAdminError(ServiceError):
    """The change would leave the installation with no live admin.

    A precondition in the Clark-Wilson sense: the transformation is refused rather
    than allowed to produce a state no integrity check could repair — there would be
    nobody able to grant the role back. 409: the request is well-formed, the current
    state forbids it.
    """

    def __init__(self, message: str) -> None:
        super().__init__(409, message)


class UsersService:
    """User management, identity and sessions over one database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    @property
    def available(self) -> bool:
        return self._db is not None and bool(getattr(self._db, "is_connected", False))

    # ── sessions ──────────────────────────────────────────────────────────────

    def authenticate(self, username: str, password: str) -> tuple[str, str] | None:
        """Return ``(user_id, role)`` for valid credentials, else None."""
        return verify_credentials_db(username, password, self._db)

    def revoke_session(self, jti: str, expires_at: datetime) -> None:
        self._db.tokens.revoke(jti, expires_at)

    def identity(self, user_id: str | None, workspace_id: str | None) -> tuple[str | None, str | None]:
        """The caller's global role and their role in the workspace (or the default one)."""
        if not user_id or user_id == "anonymous" or not self.available:
            return None, None
        ws_id = workspace_id or self._db.get_default_workspace_id()
        workspace_role = self._db.get_workspace_member_role(ws_id, user_id) if ws_id else None
        user = self._db.users.get_by_id(user_id)
        return (user.get("role") if user else None), workspace_role

    def change_own_password(self, user_id: str, current_password: str, new_password: str) -> None:
        """Replace *user_id*'s password after proving they know the current one."""
        user = self._db.users.get_by_id(user_id) if _is_uuid(user_id) else None
        if user is None:
            # The env-var bootstrap admin signs in as "admin", with no user row, so it has
            # no stored password to change. Its way out is to create a real administrator.
            raise ServiceError(
                409, "This account has no stored password. Sign in as a database user to change it."
            )
        # 400, not 401: the session is valid, only this answer is wrong. A 401 would make
        # the frontend treat a typo as an expired session and send the user to the login page.
        if not verify_user_password(self._db.users, user["username"], current_password):
            raise ServiceError(400, "Current password is incorrect")
        if not self._db.users.update(user_id, hashed_password=hash_user_password(new_password)):
            raise ServiceError(409, "The account changed while updating; try again")
        logger.info("[Auth] User %s changed their own password", user_id)

    # ── administration ────────────────────────────────────────────────────────

    def create_user(
        self,
        username: str,
        password: str,
        email: str | None,
        role: str,
        workspace_id: str | None,
        workspace_role: str,
    ) -> dict[str, Any]:
        """Create the user and, when given, their workspace membership in the same call.

        After RBAC-1 a user with no workspace is refused everything, so a create that
        succeeds and a grant that never happens produces an account that can log in and
        do nothing — exactly what the first version of the Users screen shipped.
        """
        try:
            user_id = self._db.users.create(
                username=username, hashed_password=hash_user_password(password), email=email, role=role
            )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise ServiceError(409, "Username or email already exists") from exc
            raise
        if workspace_id:
            self._db.add_workspace_member(workspace_id, user_id, workspace_role)
        return _public(self._db.users.get_by_id(user_id) or {})

    def list_users(self, include_retired: bool) -> list[dict[str, Any]]:
        return [_public(u) for u in self._db.users.list_all(include_retired=include_retired)]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        user = self._db.users.get_by_id(user_id)
        return _public(user) if user else None

    def update_user(self, user_id: str, fields: dict[str, Any], password: str | None) -> dict[str, Any] | None:
        """Apply *fields* (and a new *password*); None when there is no such user."""
        changes = dict(fields)
        if password is not None:
            changes["hashed_password"] = hash_user_password(password)
        # Demoting or deactivating the last admin locks everyone out of user,
        # model and settings management.
        demotes = changes.get("role") not in (None, "admin")
        deactivates = changes.get("is_active") is False
        if (demotes or deactivates) and self._would_remove_last_admin(user_id):
            raise LastAdminError("Cannot remove the last remaining admin")
        if not self._db.users.update(user_id, **changes):
            return None
        return self.get_user(user_id)

    def retire_user(self, user_id: str, actor: str) -> bool:
        if self._would_remove_last_admin(user_id):
            raise LastAdminError("Cannot delete the last remaining admin")
        return self._db.users.retire(user_id, deleted_by=actor)

    def purge_user(self, user_id: str) -> bool:
        return self._db.users.purge(user_id)

    def user_workspaces(self, user_id: str) -> list[dict[str, Any]]:
        workspaces: list[dict[str, Any]] = self._db.get_user_workspaces(user_id)
        return workspaces

    def grant_workspace(self, user_id: str, workspace_id: str, role: str) -> None:
        self._db.add_workspace_member(workspace_id, user_id, role)

    def revoke_workspace(self, user_id: str, workspace_id: str) -> bool:
        try:
            return bool(self._db.remove_workspace_member(workspace_id, user_id))
        except LastOwnerError as exc:
            # The message is a constant, not str(exc): nothing raised below this line
            # can reach the caller, whatever it says (CodeQL #91).
            logger.warning("[Users] revoke workspace constraint: %s", exc)
            raise ServiceError(409, _LAST_OWNER) from exc

    def _would_remove_last_admin(self, user_id: str) -> bool:
        """True when this user is the only remaining live admin.

        Enforced here rather than in the UI: a greyed-out button is a courtesy, not
        a precondition. Without this the API happily leaves an installation with no
        one able to manage users, models or settings — recoverable only by editing
        the database directly.
        """
        user = self._db.users.get_by_id(user_id)
        if not user or user.get("role") != "admin":
            return False
        return self._db.users.count_live_admins() <= 1


def _public(user: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in user.items() if k != "hashed_password"}


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
