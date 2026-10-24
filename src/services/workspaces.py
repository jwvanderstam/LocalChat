"""Workspaces, their members and their API keys: the use cases behind ``workspace_routes``.

Who may act on a workspace is still decided before a method here is called, by the
route's ``deny()`` — the one guard every workspace-scoped router shares, which also
admits workspace API keys. What lives here is what depends on the caller beyond that
yes or no: which workspaces they are shown, who owns a workspace they create, and whose
name goes on a retirement or a revocation (QP-4, ADR-7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..db.workspaces import LastOwnerError
from ..utils.logging_config import get_logger
from .errors import ServiceError

if TYPE_CHECKING:
    from ..db import Database

logger = get_logger(__name__)

#: Matches the wording the users router returns for the same refusal.
_LAST_OWNER = "Cannot remove the last owner of a workspace"


class WorkspacesService:
    """Workspace management over one database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── workspaces ────────────────────────────────────────────────────────────

    def visible_to(self, user_id: str | None) -> list[dict[str, Any]]:
        """The workspaces this caller may use: all of them for an admin, else their own.

        Everyone used to see every workspace. Selecting one you were not a member of
        produced a correct Access Denied, but the list had already told you the names
        of workspaces you have no business knowing about.
        """
        # "anonymous" means the RBAC bypass is on and there is no caller to scope by;
        # narrowing to their memberships would empty the switcher entirely.
        actor = _actor(user_id)
        if actor is None:
            return self._db.workspaces.list_all()
        # Role from the database rather than the token, matching /api/users/me: a
        # demotion takes effect immediately instead of at the next login.
        caller = self._db.users.get_by_id(actor)
        if caller and caller.get("role") == "admin":
            return self._db.workspaces.list_all()
        return self._db.members.for_user(actor)

    def create(
        self,
        name: str,
        description: str,
        system_prompt: str,
        model_class: str | None,
        creator: str | None,
    ) -> dict[str, Any] | None:
        """Create a workspace owned by *creator* and return it."""
        workspace_id = self._db.workspaces.create(
            name=name,
            description=description,
            system_prompt=system_prompt,
            model_class=model_class,
            owner_id=_actor(creator),
        )
        return self._db.workspaces.get(workspace_id)

    def get(self, workspace_id: str) -> dict[str, Any] | None:
        return self._db.workspaces.get(workspace_id)

    def update(self, workspace_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        """Apply *fields*; None when there is no such workspace."""
        if not self._db.workspaces.update(workspace_id, **fields):
            return None
        return self._db.workspaces.get(workspace_id)

    def retire(self, workspace_id: str, actor: str | None) -> bool:
        return self._db.workspaces.retire(workspace_id, deleted_by=_actor(actor))

    def default_id(self) -> str | None:
        return self._db.workspaces.default_id()

    def purge(self, workspace_id: str) -> bool:
        return self._db.workspaces.purge(workspace_id)

    # ── members ───────────────────────────────────────────────────────────────

    def members(self, workspace_id: str) -> list[dict[str, Any]]:
        return self._db.members.list_for_workspace(workspace_id)

    def set_member(self, workspace_id: str, user_id: str, role: str) -> None:
        self._db.members.add(workspace_id, user_id, role)

    def remove_member(self, workspace_id: str, user_id: str) -> bool:
        try:
            return self._db.members.remove(workspace_id, user_id)
        except LastOwnerError as exc:
            # The message is a constant, not str(exc): nothing raised below this line
            # can reach the caller, whatever it says (CodeQL #91).
            logger.warning("[Workspaces] remove member constraint: %s", exc)
            raise ServiceError(409, _LAST_OWNER) from exc

    # ── API keys ──────────────────────────────────────────────────────────────

    def keys(self, workspace_id: str) -> list[dict[str, Any]]:
        return self._db.api_keys.list_for_workspace(workspace_id)

    def create_key(
        self, workspace_id: str, name: str, role: str, creator: str | None
    ) -> tuple[str, dict[str, Any]]:
        """Return ``(full_key, row)``; the plaintext key exists only in this answer."""
        return self._db.api_keys.create(
            workspace_id=workspace_id, name=name, role=role, created_by=_actor(creator)
        )

    def revoke_key(self, workspace_id: str, key_id: str, actor: str | None) -> bool:
        return self._db.api_keys.revoke(
            key_id=key_id, workspace_id=workspace_id, revoked_by=_actor(actor)
        )


def _actor(user_id: str | None) -> str | None:
    """The user to record, or None for no caller and for the RBAC bypass's "anonymous"."""
    return user_id if user_id and user_id != "anonymous" else None
