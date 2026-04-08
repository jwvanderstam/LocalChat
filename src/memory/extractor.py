"""
Memory Extractor
================

Analyses a conversation and extracts structured long-term memories via an LLM
call.  Each memory is embedded and deduplicated against existing ones before
being stored.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..utils.logging_config import get_logger

logger = get_logger(__name__)

_EXTRACT_SYSTEM = """\
You are a memory extractor.  Read the conversation below and extract reusable
facts, user preferences, decisions made, and named entities worth remembering.

Output ONLY a JSON array (no prose before or after).  Each element must have:
{
  "content": "<concise one-sentence memory>",
  "memory_type": "<fact|preference|decision|entity>",
  "confidence": <0.0–1.0>
}

Rules:
- Omit trivial, generic, or unhelpful items.
- confidence = 1.0 for definitive statements; lower for uncertain ones.
- Max 10 memories per conversation.
- If nothing worth remembering exists output: []
"""

_JSON_ARRAY_RE = re.compile(r'\[.*\]', re.DOTALL)


class MemoryExtractor:
    """Extract memories from a list of conversation messages."""

    def extract(
        self,
        conversation_id: str,
        messages: list[dict[str, str]],
        model: str,
        ollama_client: Any,
        db: Any,
    ) -> int:
        """
        Extract and persist memories from a conversation.

        Args:
            conversation_id: UUID string of the source conversation.
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            model: Active Ollama model name.
            ollama_client: OllamaClient instance.
            db: Database instance.

        Returns:
            Number of new memories stored.
        """
        if not messages:
            db.mark_conversation_extracted(conversation_id)
            return 0

        # Build a transcript for the LLM
        transcript_parts = []
        for m in messages:
            role = m.get('role', 'user').capitalize()
            content = (m.get('content') or '').strip()
            if content:
                transcript_parts.append(f"{role}: {content[:500]}")  # cap per turn

        if not transcript_parts:
            db.mark_conversation_extracted(conversation_id)
            return 0

        transcript = "\n".join(transcript_parts[-20:])  # last 20 turns max

        try:
            raw_memories = self._call_llm(transcript, model, ollama_client)
        except Exception as exc:
            logger.warning(f"[Memory] LLM extraction failed for conv {conversation_id}: {exc}")
            db.mark_conversation_extracted(conversation_id)
            return 0

        inserted = 0
        for item in raw_memories:
            content = str(item.get("content") or "").strip()
            memory_type = str(item.get("memory_type") or "fact")
            confidence = float(item.get("confidence") or 1.0)
            if not content or len(content) < 5:
                continue
            try:
                ok, embedding = ollama_client.generate_embedding(
                    ollama_client.get_embedding_model(), content
                )
                if not ok or not embedding:
                    continue
                if db.is_duplicate_memory(embedding):
                    logger.debug(f"[Memory] Skipping duplicate: {content[:60]}")
                    continue
                db.insert_memory(
                    content=content,
                    embedding=embedding,
                    source_conv_id=conversation_id,
                    memory_type=memory_type,
                    confidence=confidence,
                )
                inserted += 1
            except Exception as exc:
                logger.warning(f"[Memory] Failed to store memory: {exc}")

        db.mark_conversation_extracted(conversation_id)
        logger.info(f"[Memory] Extracted {inserted} new memories from conv {conversation_id}")
        return inserted

    @staticmethod
    def _call_llm(transcript: str, model: str, ollama_client: Any) -> list[dict]:
        """Call the LLM and parse the JSON array response."""
        prompt_messages = [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user",   "content": f"Conversation:\n{transcript}"},
        ]
        raw = next(iter(
            ollama_client.generate_chat_response(
                model, prompt_messages, stream=False, temperature=0.0
            )
        ), "")
        match = _JSON_ARRAY_RE.search(raw.strip())
        if not match:
            logger.debug(f"[Memory] No JSON array in LLM output: {raw[:120]!r}")
            return []
        return json.loads(match.group(0))
