"""The global knowledge tier: the use cases behind ``gkb_routes`` (GKB-2, QP-4, ADR-7).

Contributing needs a global admin and withdrawing a workspace owner; both are decided by
the route before a method here is called (decided 2026-10-19, the reasoning of D3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .errors import ServiceError

if TYPE_CHECKING:
    from ..db import Database


class ContributionsService:
    """Contributing, withdrawing and listing global-tier documents over one database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def contribute(self, workspace_id: str, document_ids: list[int], admin_id: str) -> list[dict[str, Any]]:
        """Copy the documents into the global tier, or refuse the whole selection."""
        if self._db.workspaces.get(workspace_id) is None:
            raise ServiceError(404, "Workspace not found")
        contributed = self._db.contributions.contribute(workspace_id, document_ids, admin_id)
        if contributed is None:
            raise ServiceError(404, "Every document must be a live document of this workspace")
        return contributed

    def archive(self, workspace_id: str, caller: str) -> int:
        return self._db.contributions.archive(workspace_id, caller)

    def list_all(self) -> list[dict[str, Any]]:
        return self._db.contributions.list_all()
