"""Long-term memories: the use cases behind ``longterm_memory_routes`` (QP-4, ADR-7).

Who may act is decided before a method here is called, by the route's ``deny()``; every
method takes the ``Scope`` that guard authorised. Retrieval of memories for a chat is
``src/memory/retriever.py``'s, which reads through the same repository.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..utils.logging_config import get_logger
from ..utils.scope import Scope

if TYPE_CHECKING:
    from ..db import Database

logger = get_logger(__name__)


class MemoriesService:
    """Listing, extracting and retiring long-term memories over one database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def list_page(self, limit: int, offset: int, scope: Scope) -> list[dict[str, Any]]:
        return self._db.memories.list_page(limit=limit, offset=offset, scope=scope)

    async def extract(self, limit: int, scope: Scope, model: str, ollama_client: Any) -> dict[str, int]:
        """Extract memories from up to *limit* conversations not yet read; returns the counts.

        *ollama_client* is ``Any`` because the extractor takes it untyped; it is the
        application's ``OllamaClient`` singleton.
        """
        from ..memory.extractor import MemoryExtractor

        extractor = MemoryExtractor()
        conversations = self._db.memories.unextracted_conversations(limit=limit, scope=scope)
        total_new = processed = 0
        for conv in conversations:
            try:
                messages = self._db.conversations.messages(conv["id"], scope=scope)
                if messages is None:
                    raise LookupError("conversation retired while extracting")
                msg_list = []
                for m in messages:
                    if isinstance(m, dict):
                        msg_list.append({"role": m.get("role", ""), "content": m.get("content", "")})
                    elif isinstance(m, (list, tuple)) and len(m) >= 2:
                        msg_list.append({"role": m[0], "content": m[1]})
                total_new += await extractor.extract(
                    conversation_id=conv["id"],
                    messages=msg_list,
                    model=model,
                    ollama_client=ollama_client,
                    db=self._db,
                    workspace_id=conv.get("workspace_id"),
                )
                processed += 1
            except Exception:  # noqa: BLE001 — per-conversation extraction in a batch; one failure must not abandon the rest
                logger.warning("[Memory] Extraction failed for conv %s", conv["id"], exc_info=True)
        return {"conversations_processed": processed, "new_memories": total_new}

    def retire(self, memory_id: str, actor: str | None, scope: Scope) -> bool:
        return self._db.memories.retire(memory_id, deleted_by=_actor(actor), scope=scope)

    def retire_all(self, actor: str | None, scope: Scope) -> int:
        return self._db.memories.retire_all(deleted_by=_actor(actor), scope=scope)


def _actor(user_id: str | None) -> str | None:
    """The user to record, or None for no caller and for the RBAC bypass's "anonymous"."""
    return user_id if user_id and user_id != "anonymous" else None
