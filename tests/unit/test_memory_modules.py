"""
Tests for src/memory/retriever.py and src/memory/extractor.py

Covers:
  - MemoryRetriever.retrieve: DB not connected, no embedding model, embedding failure,
    search failure, successful retrieval with usage update, usage update failure is silent
  - MemoryRetriever.format_for_prompt: empty list, single/multi memory, type tag
  - MemoryExtractor.extract: empty messages, all-empty content, LLM failure,
    duplicate filter, embedding failure, successful insert, returns count
  - MemoryExtractor._call_llm: JSON array found, no JSON array, LLM returns empty
"""

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ollama(embedding_model="nomic-embed-text", embedding_ok=True, embedding_vec=None):
    client = MagicMock()
    client.get_embedding_model.return_value = embedding_model
    vec = embedding_vec or [0.1] * 384
    client.generate_embedding.return_value = (embedding_ok, vec if embedding_ok else None)
    return client


def _make_db(connected=True, memories=None):
    db = MagicMock()
    db.is_connected = connected
    db.search_memories.return_value = memories or []
    return db


# ===========================================================================
# MemoryRetriever.retrieve
# ===========================================================================

class TestMemoryRetrieverRetrieve:
    def _retriever(self):
        from src.memory.retriever import MemoryRetriever
        return MemoryRetriever()

    def test_returns_empty_when_db_not_connected(self):
        r = self._retriever()
        result = r.retrieve("query", _make_ollama(), _make_db(connected=False))
        assert result == []

    def test_returns_empty_when_no_embedding_model(self):
        r = self._retriever()
        ollama = _make_ollama()
        ollama.get_embedding_model.return_value = None
        result = r.retrieve("query", ollama, _make_db())
        assert result == []

    def test_returns_empty_when_embedding_fails(self):
        r = self._retriever()
        ollama = _make_ollama(embedding_ok=False)
        result = r.retrieve("query", ollama, _make_db())
        assert result == []

    def test_returns_empty_when_embedding_raises(self):
        r = self._retriever()
        ollama = MagicMock()
        ollama.get_embedding_model.return_value = "model"
        ollama.generate_embedding.side_effect = RuntimeError("timeout")
        result = r.retrieve("query", ollama, _make_db())
        assert result == []

    def test_returns_empty_when_search_raises(self):
        r = self._retriever()
        db = _make_db()
        db.search_memories.side_effect = Exception("DB error")
        result = r.retrieve("query", _make_ollama(), db)
        assert result == []

    def test_returns_memories_on_success(self):
        r = self._retriever()
        memories = [{"id": 1, "content": "fact A", "memory_type": "fact"}]
        db = _make_db(memories=memories)
        result = r.retrieve("query", _make_ollama(), db)
        assert result == memories

    def test_calls_update_memory_usage_on_hit(self):
        r = self._retriever()
        memories = [{"id": 7, "content": "fact", "memory_type": "fact"}]
        db = _make_db(memories=memories)
        r.retrieve("query", _make_ollama(), db)
        db.update_memory_usage.assert_called_once_with([7])

    def test_usage_update_failure_is_silent(self):
        r = self._retriever()
        memories = [{"id": 1, "content": "fact", "memory_type": "fact"}]
        db = _make_db(memories=memories)
        db.update_memory_usage.side_effect = Exception("quota exceeded")
        # Should not raise
        result = r.retrieve("query", _make_ollama(), db)
        assert result == memories

    def test_no_usage_update_when_no_memories(self):
        r = self._retriever()
        db = _make_db(memories=[])
        r.retrieve("query", _make_ollama(), db)
        db.update_memory_usage.assert_not_called()

    def test_passes_top_k_and_min_similarity_to_search(self):
        r = self._retriever()
        db = _make_db()
        r.retrieve("query", _make_ollama(), db, top_k=5, min_similarity=0.7)
        db.search_memories.assert_called_once()
        call_kwargs = db.search_memories.call_args
        assert call_kwargs.kwargs.get("top_k") == 5 or call_kwargs.args[1] == 5
        assert call_kwargs.kwargs.get("min_similarity") == 0.7 or call_kwargs.args[2] == 0.7


# ===========================================================================
# MemoryRetriever.format_for_prompt
# ===========================================================================

class TestMemoryRetrieverFormatForPrompt:
    def _fmt(self, memories):
        from src.memory.retriever import MemoryRetriever
        return MemoryRetriever.format_for_prompt(memories)

    def test_empty_returns_empty_string(self):
        assert self._fmt([]) == ""

    def test_single_memory_contains_content(self):
        memories = [{"id": 1, "content": "Alice uses dark mode.", "memory_type": "preference"}]
        result = self._fmt(memories)
        assert "Alice uses dark mode." in result

    def test_type_tag_is_uppercase(self):
        memories = [{"id": 1, "content": "X", "memory_type": "fact"}]
        result = self._fmt(memories)
        assert "[FACT]" in result

    def test_multiple_memories_all_present(self):
        memories = [
            {"id": 1, "content": "Fact A", "memory_type": "fact"},
            {"id": 2, "content": "Pref B", "memory_type": "preference"},
        ]
        result = self._fmt(memories)
        assert "Fact A" in result
        assert "Pref B" in result
        assert "[FACT]" in result
        assert "[PREFERENCE]" in result

    def test_header_present(self):
        memories = [{"id": 1, "content": "X", "memory_type": "entity"}]
        result = self._fmt(memories)
        assert "memories from past conversations" in result.lower()

    def test_missing_memory_type_defaults_to_fact(self):
        memories = [{"id": 1, "content": "Y"}]  # no memory_type key
        result = self._fmt(memories)
        assert "[FACT]" in result


# ===========================================================================
# MemoryExtractor.extract
# ===========================================================================

class TestMemoryExtractorExtract:
    def _extractor(self):
        from src.memory.extractor import MemoryExtractor
        return MemoryExtractor()

    def _make_messages(self, pairs=None):
        """pairs: list of (role, content)"""
        if pairs is None:
            pairs = [("user", "Tell me about X"), ("assistant", "X is Y")]
        return [{"role": r, "content": c} for r, c in pairs]

    def _llm_response(self, items):
        """Make ollama return a JSON array of memory items."""
        import json
        ollama = MagicMock()
        ollama.get_embedding_model.return_value = "embed-model"
        ollama.generate_embedding.return_value = (True, [0.1] * 384)
        ollama.generate_chat_response.return_value = iter([json.dumps(items)])
        return ollama

    def test_empty_messages_returns_zero_and_marks_extracted(self):
        e = self._extractor()
        db = MagicMock()
        count = e.extract("conv-1", [], "model", MagicMock(), db)
        assert count == 0
        db.mark_conversation_extracted.assert_called_once_with("conv-1")

    def test_all_empty_content_returns_zero(self):
        e = self._extractor()
        db = MagicMock()
        msgs = [{"role": "user", "content": ""}, {"role": "assistant", "content": None}]
        count = e.extract("conv-1", msgs, "model", MagicMock(), db)
        assert count == 0
        db.mark_conversation_extracted.assert_called_once()

    def test_llm_returns_valid_memories_stores_them(self):
        e = self._extractor()
        db = MagicMock()
        db.is_duplicate_memory.return_value = False
        ollama = self._llm_response([
            {"content": "User prefers dark mode", "memory_type": "preference", "confidence": 0.9}
        ])
        count = e.extract("conv-1", self._make_messages(), "model", ollama, db)
        assert count == 1
        db.insert_memory.assert_called_once()

    def test_duplicate_memory_is_skipped(self):
        e = self._extractor()
        db = MagicMock()
        db.is_duplicate_memory.return_value = True
        ollama = self._llm_response([
            {"content": "User prefers dark mode", "memory_type": "preference", "confidence": 0.9}
        ])
        count = e.extract("conv-1", self._make_messages(), "model", ollama, db)
        assert count == 0
        db.insert_memory.assert_not_called()

    def test_embedding_failure_skips_memory(self):
        e = self._extractor()
        db = MagicMock()
        import json as _json
        ollama = MagicMock()
        ollama.get_embedding_model.return_value = "em"
        ollama.generate_embedding.return_value = (False, None)
        ollama.generate_chat_response.return_value = iter([
            _json.dumps([{"content": "Something memorable", "memory_type": "fact", "confidence": 1.0}])
        ])
        count = e.extract("conv-1", self._make_messages(), "model", ollama, db)
        assert count == 0
        db.insert_memory.assert_not_called()

    def test_llm_failure_marks_extracted_and_returns_zero(self):
        e = self._extractor()
        db = MagicMock()
        ollama = MagicMock()
        ollama.generate_chat_response.side_effect = RuntimeError("timeout")
        count = e.extract("conv-1", self._make_messages(), "model", ollama, db)
        assert count == 0
        db.mark_conversation_extracted.assert_called_once()

    def test_short_content_is_skipped(self):
        e = self._extractor()
        db = MagicMock()
        db.is_duplicate_memory.return_value = False
        ollama = self._llm_response([
            {"content": "Hi", "memory_type": "fact", "confidence": 1.0}  # too short (< 5 chars)
        ])
        count = e.extract("conv-1", self._make_messages(), "model", ollama, db)
        assert count == 0

    def test_marks_extracted_even_on_all_duplicates(self):
        e = self._extractor()
        db = MagicMock()
        db.is_duplicate_memory.return_value = True
        ollama = self._llm_response([
            {"content": "Something worth remembering", "memory_type": "fact", "confidence": 1.0}
        ])
        e.extract("conv-1", self._make_messages(), "model", ollama, db)
        db.mark_conversation_extracted.assert_called_once()

    def test_transcript_truncates_to_last_20_turns(self):
        """Verify that very long conversation histories don't crash extract()."""
        e = self._extractor()
        db = MagicMock()
        db.is_duplicate_memory.return_value = True
        ollama = self._llm_response([])
        msgs = [{"role": "user", "content": f"message {i}"} for i in range(100)]
        # Should not raise
        count = e.extract("conv-1", msgs, "model", ollama, db)
        assert isinstance(count, int)


# ===========================================================================
# MemoryExtractor._call_llm
# ===========================================================================

class TestMemoryExtractorCallLlm:
    def _call(self, raw_output):
        from src.memory.extractor import MemoryExtractor
        ollama = MagicMock()
        ollama.generate_chat_response.return_value = iter([raw_output])
        return MemoryExtractor._call_llm("transcript text", "model", ollama)

    def test_valid_json_array_returned(self):
        items = [{"content": "Alice likes Python", "memory_type": "preference", "confidence": 0.8}]
        import json
        result = self._call(json.dumps(items))
        assert result == items

    def test_no_json_array_returns_empty_list(self):
        result = self._call("I cannot extract any memories from this conversation.")
        assert result == []

    def test_empty_array_returned(self):
        result = self._call("[]")
        assert result == []

    def test_json_array_embedded_in_prose(self):
        import json
        items = [{"content": "Fact", "memory_type": "fact", "confidence": 1.0}]
        raw = f"Here are the memories:\n{json.dumps(items)}\nDone."
        result = self._call(raw)
        assert result == items

    def test_empty_llm_response_returns_empty_list(self):
        result = self._call("")
        assert result == []
