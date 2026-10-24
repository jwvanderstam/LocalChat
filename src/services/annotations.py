"""Annotations on chunks: the use cases behind ``annotation_routes`` (QP-4, ADR-7).

Who may act is the route's ``deny()``; listing and retiring take the ``Scope`` that guard
authorised.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..utils.scope import Scope

if TYPE_CHECKING:
    from ..db import Database


class AnnotationsService:
    """Adding, listing and retiring annotations over one database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def add(
        self, chunk_id: int, text: str, user_id: str | None, conversation_id: str | None, scope: Scope
    ) -> str:
        return self._db.annotations.add(
            chunk_id=chunk_id, text=text, user_id=user_id, conversation_id=conversation_id, scope=scope,
        )

    def for_chunk(self, chunk_id: int, scope: Scope) -> list[dict[str, Any]] | None:
        """The chunk's annotations, or None when *scope* holds no such chunk.

        The chunk is resolved first so a chunk outside this scope reads as not found,
        rather than as a chunk with no annotations. The annotation query joins on the
        document's workspace and so never leaked anything — but answering 200 for someone
        else's chunk still told the caller it exists.
        """
        if self._db.documents.chunk_by_id(chunk_id, scope=scope) is None:
            return None
        return self._db.annotations.for_chunk(chunk_id, scope=scope)

    def retire(self, annotation_id: str, user_id: str | None, scope: Scope) -> bool:
        deleted_by = user_id if user_id and user_id != "anonymous" else None
        return self._db.annotations.retire(
            annotation_id, user_id=user_id, deleted_by=deleted_by, scope=scope
        )
