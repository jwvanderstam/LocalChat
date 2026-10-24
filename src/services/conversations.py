"""Conversations: the use cases behind ``memory_routes`` (QP-4, ADR-7).

Who may act is decided before a method here is called, by the route's ``deny()`` or
``require_admin_dep``; every method that reads or changes a workspace's conversations
takes the ``Scope`` that guard authorised. Sending a chat message is
``src/services/chat.py``'s, which writes through the same repository.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..utils.scope import Scope

if TYPE_CHECKING:
    from ..db import Database


class ConversationsService:
    """Listing, reading, renaming, filtering, retiring and purging conversations."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def page(self, limit: int, offset: int, scope: Scope) -> dict[str, Any]:
        """One page of conversations, with the total so a caller can tell a full page from the end."""
        conversations = self._db.conversations.list_page(limit=limit, offset=offset, scope=scope)
        total = self._db.conversations.count(scope=scope)
        return {
            "conversations": conversations,
            "limit": limit,
            "offset": offset,
            "total": total,
            "has_more": offset + len(conversations) < total,
        }

    def create(self, title: str, workspace_id: str | None) -> str:
        return self._db.conversations.create(title, workspace_id=workspace_id)

    def messages(self, conversation_id: str, scope: Scope) -> list[dict[str, Any]] | None:
        """The conversation's messages, or None when *scope* holds no such conversation."""
        return self._db.conversations.messages(conversation_id, scope=scope)

    def document_filter(self, conversation_id: str, scope: Scope) -> list[str] | None:
        return self._db.conversations.document_filter(conversation_id, scope=scope)

    def set_document_filter(self, conversation_id: str, filenames: list[str], scope: Scope) -> bool:
        return self._db.conversations.set_document_filter(conversation_id, filenames, scope=scope)

    def set_title(self, conversation_id: str, title: str, scope: Scope) -> bool:
        return self._db.conversations.set_title(conversation_id, title, scope=scope)

    def retire(self, conversation_id: str, actor: str | None, scope: Scope) -> bool:
        return self._db.conversations.retire(conversation_id, deleted_by=_actor(actor), scope=scope)

    def retire_all(self, actor: str | None, scope: Scope) -> int:
        return self._db.conversations.retire_all(deleted_by=_actor(actor), scope=scope)

    def purge(self, conversation_id: str) -> bool:
        return self._db.conversations.purge(conversation_id)


def _actor(user_id: str | None) -> str | None:
    """The user to record, or None for no caller and for the RBAC bypass's "anonymous"."""
    return user_id if user_id and user_id != "anonymous" else None
