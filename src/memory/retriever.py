"""
Memory Retriever
================

Query-time memory lookup: embeds the query, searches the memories table, and
formats the top-K results for injection into the LLM system prompt.
"""

from __future__ import annotations

from typing import Any

from ..utils.logging_config import get_logger

logger = get_logger(__name__)

_MEMORY_SECTION_HEADER = (
    "Relevant memories from past conversations (use as background context):"
)


class MemoryRetriever:
    """Retrieve memories relevant to a query and format them for prompt injection."""

    def retrieve(
        self,
        query: str,
        ollama_client: Any,
        db: Any,
        top_k: int = 3,
        min_similarity: float = 0.55,
    ) -> list[dict]:
        """
        Return top-k memories relevant to *query*.

        Args:
            query: User query string.
            ollama_client: OllamaClient instance.
            db: Database instance.
            top_k: Maximum memories to return.
            min_similarity: Minimum cosine similarity threshold.

        Returns:
            List of memory dicts (may be empty).
        """
        if not db.is_connected:
            return []

        embedding_model = ollama_client.get_embedding_model()
        if not embedding_model:
            return []

        try:
            ok, embedding = ollama_client.generate_embedding(embedding_model, query)
            if not ok or not embedding:
                return []
        except Exception as exc:
            logger.debug(f"[Memory] Embedding failed for retrieval: {exc}")
            return []

        try:
            memories = db.search_memories(embedding, top_k=top_k, min_similarity=min_similarity)
        except Exception as exc:
            logger.warning(f"[Memory] Search failed: {exc}")
            return []

        if memories:
            try:
                db.update_memory_usage([m["id"] for m in memories])
            except Exception:
                pass  # non-critical
            logger.info(f"[Memory] Retrieved {len(memories)} memories for prompt injection")

        return memories

    @staticmethod
    def format_for_prompt(memories: list[dict]) -> str:
        """Return a formatted string for insertion into a system prompt."""
        if not memories:
            return ""
        lines = [_MEMORY_SECTION_HEADER]
        for m in memories:
            tag = m.get("memory_type", "fact").upper()
            lines.append(f"[{tag}] {m['content']}")
        return "\n".join(lines)
