"""Documents and their chunks: the use cases behind ``document_routes`` (QP-4, ADR-7).

Who may act is decided before a method here is called, by the route's ``deny()`` or
``require_admin_dep``; every method that reads or retires a workspace's documents takes
the ``Scope`` that guard authorised, and nothing here widens it. Upload and ingest go
through ``DocumentProcessor``, which is QP-5's to split.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from ..db.connection import DatabaseUnavailableError
from ..utils.logging_config import get_logger
from ..utils.scope import Scope
from .errors import ServiceError

if TYPE_CHECKING:
    from ..db import Database

logger = get_logger(__name__)


@contextmanager
def _database_required() -> Iterator[None]:
    """A database that cannot answer is a 503, not the route's generic 500."""
    try:
        yield
    except DatabaseUnavailableError as exc:
        logger.exception("[Documents] database unavailable")
        raise ServiceError(503, "Database unavailable") from exc


class DocumentsService:
    """Listing, inspecting, retiring and purging documents over one database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def count(self, scope: Scope) -> int:
        return self._db.documents.count(scope=scope)

    def list_all(self, scope: Scope) -> list[dict[str, Any]]:
        with _database_required():
            return self._db.documents.list_all(scope=scope)

    def stats(self, scope: Scope) -> dict[str, Any]:
        with _database_required():
            return {
                "document_count": self._db.documents.count(scope=scope),
                "chunk_count": self._db.documents.chunk_count(scope=scope),
                "chunk_statistics": self._db.documents.chunk_statistics(),
            }

    def search_text(self, text: str, limit: int, scope: Scope) -> list[dict[str, Any]]:
        return self._db.documents.search_text(text, limit, scope=scope)

    def chunk_context(self, chunk_id: int, window: int, scope: Scope) -> dict[str, Any] | None:
        """The chunk and its neighbours within *window*; None when *scope* has no such chunk."""
        chunk = self._db.documents.chunk_by_id(chunk_id, scope=scope)
        if chunk is None:
            return None
        adjacent = self._db.documents.adjacent_chunks(
            chunk["document_id"], chunk["chunk_index"], window_size=window, scope=scope
        )
        return {
            "document_id": chunk["document_id"],
            "chunk_index": chunk["chunk_index"],
            "chunks": [{"chunk_text": text, "chunk_index": idx} for text, idx in adjacent],
        }

    def retire(self, doc_id: int, actor: str | None, scope: Scope) -> bool:
        with _database_required():
            return self._db.documents.retire(doc_id, _actor(actor), scope=scope)

    def retire_all(self, actor: str | None, scope: Scope) -> int:
        with _database_required():
            return self._db.documents.retire_all(scope=scope, deleted_by=_actor(actor))

    def purge(self, doc_id: int) -> bool:
        with _database_required():
            return self._db.documents.purge(doc_id)

    def purge_all(self) -> int:
        with _database_required():
            return self._db.documents.purge_all()


def _actor(user_id: str | None) -> str | None:
    """The user to record, or None for no caller and for the RBAC bypass's "anonymous"."""
    return user_id if user_id and user_id != "anonymous" else None
