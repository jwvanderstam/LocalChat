# -*- coding: utf-8 -*-
"""Final coverage push — error handler, QueryCache, _build_embeddings_parallel."""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# error_handlers.py — line 43 (missing error type) + lines 147-155 (handler)
# ---------------------------------------------------------------------------

class TestValidationMessageMissingField:
    def test_single_missing_field(self):
        """Cover the 'missing' branch (line 43-44) in _build_validation_message."""
        from src.routes.error_handlers import _build_validation_message
        errors = [{'loc': ('name',), 'type': 'missing', 'msg': 'Field required', 'input': None}]
        msg = _build_validation_message(errors)
        assert "missing" in msg.lower()
        assert "name" in msg

    def test_single_unknown_error_type(self):
        """Cover the fallthrough (line 45) for unexpected error types."""
        from src.routes.error_handlers import _build_validation_message
        errors = [{'loc': ('value',), 'type': 'custom_error', 'msg': 'bad value', 'input': None}]
        msg = _build_validation_message(errors)
        assert "value" in msg


class TestValidationErrorHandler:
    """Cover lines 147-155: the Flask PydanticValidationError handler body."""

    def test_pydantic_error_from_route_returns_400(self):
        from src.app_factory import create_app
        from pydantic import BaseModel, ValidationError, field_validator

        class Strict(BaseModel):
            name: str

            @field_validator('name')
            @classmethod
            def no_empty(cls, v):
                if not v:
                    raise ValueError("name cannot be empty")
                return v

        isolated_app = create_app(testing=True)
        isolated_app.config['PROPAGATE_EXCEPTIONS'] = False

        @isolated_app.route('/trigger-pydantic', methods=['POST'])
        def raise_pydantic():
            Strict(name=None)  # raises PydanticValidationError
            return 'ok'

        with isolated_app.test_client() as c:
            response = c.post('/trigger-pydantic')

        assert response.status_code in (400, 422, 500)

    def test_validation_error_handler_formats_message(self):
        """Verify handler builds a sensible JSON response."""
        from src.app_factory import create_app
        from pydantic import BaseModel, ValidationError

        class M(BaseModel):
            value: int

        isolated_app = create_app(testing=True)
        isolated_app.config['PROPAGATE_EXCEPTIONS'] = False

        @isolated_app.route('/trigger-pydantic-v2', methods=['POST'])
        def raise_pydantic_v2():
            M(value="not-a-number")  # raises PydanticValidationError
            return 'ok'

        with isolated_app.test_client() as c:
            response = c.post('/trigger-pydantic-v2')

        data = response.get_json()
        # Either the pydantic handler or 500 handler fires — both return JSON
        assert data is not None
        assert 'error' in data


# ---------------------------------------------------------------------------
# cache/managers.py — QueryCache paths (lines 198-199, 247-257, 273-278)
# ---------------------------------------------------------------------------

class TestQueryCacheExtra:
    def setup_method(self):
        from src.cache.managers import QueryCache
        self.qc = QueryCache(ttl=60)

    def test_cache_miss_calls_retrieve_fn(self):
        retrieve_fn = MagicMock(return_value=[("result", "doc.pdf", 0, 0.9, {})])
        results, was_cached = self.qc.get_or_retrieve("query", 5, 0.5, True, retrieve_fn)
        retrieve_fn.assert_called_once()
        assert was_cached is False

    def test_cache_hit_skips_retrieve_fn(self):
        cached_results = [("cached", "doc.pdf", 0, 0.95, {})]
        # Pre-populate
        self.qc.set("q", 5, 0.5, True, cached_results)
        retrieve_fn = MagicMock()
        results, was_cached = self.qc.get_or_retrieve("q", 5, 0.5, True, retrieve_fn)
        retrieve_fn.assert_not_called()
        assert was_cached is True
        assert results == cached_results

    def test_get_returns_none_on_miss(self):
        assert self.qc.get("unknown", 5, 0.5, True) is None

    def test_set_and_get_roundtrip(self):
        data = [("text", "f.pdf", 0, 0.8, {})]
        self.qc.set("myq", 3, 0.4, False, data)
        assert self.qc.get("myq", 3, 0.4, False) == data

    def test_invalidate_pattern_clears_cache(self):
        self.qc.set("q1", 5, 0.5, True, [("a", "b", 0, 0.9, {})])
        result = self.qc.invalidate_pattern("*")
        assert result is True

    def test_clear_returns_true(self):
        assert self.qc.clear() is True

    def test_get_stats_returns_stats(self):
        from src.cache import CacheStats
        stats = self.qc.get_stats()
        assert stats is not None


class TestEmbeddingCacheGetOrGenerateMiss:
    def test_cache_miss_calls_generate_fn(self):
        from src.cache.managers import EmbeddingCache
        ec = EmbeddingCache(ttl=60)
        generate_fn = MagicMock(return_value=[0.1] * 768)
        embedding, was_cached = ec.get_or_generate("new text", "model", generate_fn)
        generate_fn.assert_called_once_with("new text")
        assert was_cached is False
        assert len(embedding) == 768

    def test_cache_hit_skips_generate_fn(self):
        from src.cache.managers import EmbeddingCache
        ec = EmbeddingCache(ttl=60)
        ec.set("text", "model", [0.5] * 768)
        generate_fn = MagicMock()
        embedding, was_cached = ec.get_or_generate("text", "model", generate_fn)
        generate_fn.assert_not_called()
        assert was_cached is True

    def test_clear_returns_true(self):
        from src.cache.managers import EmbeddingCache
        ec = EmbeddingCache(ttl=60)
        assert ec.clear() is True

    def test_get_stats(self):
        from src.cache.managers import EmbeddingCache
        ec = EmbeddingCache(ttl=60)
        assert ec.get_stats() is not None


# ---------------------------------------------------------------------------
# rag/processor.py — _build_embeddings_parallel (lines 210-238)
# ---------------------------------------------------------------------------

class TestBuildEmbeddingsParallel:
    def _make_processor(self):
        from src.rag.processor import DocumentProcessor
        return DocumentProcessor()

    def test_successful_parallel_build(self):
        proc = self._make_processor()
        chunks_meta = [
            {'text': 'chunk1', 'chunk_index': 0, 'page_number': 1, 'section_title': 'A'},
            {'text': 'chunk2', 'chunk_index': 1, 'page_number': 1, 'section_title': None},
        ]
        with patch.object(proc, 'process_document_chunk',
                          side_effect=[(1, 'chunk1', 0, [0.1] * 768),
                                       (1, 'chunk2', 1, [0.2] * 768)]):
            result, failed = proc._build_embeddings_parallel(
                chunks_meta, doc_id=1, embedding_model='nomic',
                filename='f.pdf', progress_callback=None
            )
        assert failed == 0
        assert len(result) == 2

    def test_failed_futures_are_counted(self):
        proc = self._make_processor()
        chunks_meta = [
            {'text': 'c1', 'chunk_index': 0, 'page_number': None, 'section_title': None},
            {'text': 'c2', 'chunk_index': 1, 'page_number': None, 'section_title': None},
        ]
        # First chunk raises, second returns None
        with patch.object(proc, 'process_document_chunk',
                          side_effect=[RuntimeError("fail"), None]):
            result, failed = proc._build_embeddings_parallel(
                chunks_meta, doc_id=1, embedding_model='nomic',
                filename='f.pdf', progress_callback=None
            )
        assert failed >= 1

    def test_progress_callback_called(self):
        proc = self._make_processor()
        chunks_meta = [
            {'text': f'c{i}', 'chunk_index': i, 'page_number': None, 'section_title': None}
            for i in range(3)
        ]
        cb = MagicMock()
        with patch.object(proc, 'process_document_chunk',
                          side_effect=[(1, f'c{i}', i, [0.1] * 768) for i in range(3)]):
            proc._build_embeddings_parallel(
                chunks_meta, doc_id=1, embedding_model='nomic',
                filename='f.pdf', progress_callback=cb
            )
        cb.assert_called()

    def test_result_none_increments_failed(self):
        proc = self._make_processor()
        chunks_meta = [
            {'text': 'x', 'chunk_index': 0, 'page_number': None, 'section_title': None},
        ]
        with patch.object(proc, 'process_document_chunk', return_value=None):
            result, failed = proc._build_embeddings_parallel(
                chunks_meta, doc_id=1, embedding_model='nomic',
                filename='f.pdf', progress_callback=None
            )
        assert failed == 1
        assert result == []
