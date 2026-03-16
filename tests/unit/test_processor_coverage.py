# -*- coding: utf-8 -*-
"""Coverage for rag/processor.py uncovered paths."""

import pytest
from unittest.mock import MagicMock, patch


def _make_processor():
    from src.rag.processor import DocumentProcessor
    return DocumentProcessor()


# ---------------------------------------------------------------------------
# _load_document_chunks
# ---------------------------------------------------------------------------

class TestLoadDocumentChunks:
    def test_pdf_success_returns_chunks(self):
        proc = _make_processor()
        pages = [{"page_number": 1, "text": "content", "section_title": None}]
        chunks = [{"text": "chunk", "page_number": 1, "section_title": None, "chunk_index": 0}]
        with patch.object(proc, '_load_pdf_with_pages', return_value=(True, pages)), \
             patch.object(proc, 'chunk_pages_with_metadata', return_value=chunks):
            ok, msg, result = proc._load_document_chunks('/f.pdf', 'f.pdf', '.pdf', None)
        assert ok is True
        assert result == chunks

    def test_pdf_load_failure(self):
        proc = _make_processor()
        with patch.object(proc, '_load_pdf_with_pages', return_value=(False, "corrupt")):
            ok, msg, result = proc._load_document_chunks('/f.pdf', 'f.pdf', '.pdf', None)
        assert ok is False
        assert result is None

    def test_pdf_no_chunks_returns_false(self):
        proc = _make_processor()
        pages = [{"page_number": 1, "text": "x", "section_title": None}]
        with patch.object(proc, '_load_pdf_with_pages', return_value=(True, pages)), \
             patch.object(proc, 'chunk_pages_with_metadata', return_value=[]):
            ok, msg, result = proc._load_document_chunks('/f.pdf', 'f.pdf', '.pdf', None)
        assert ok is False

    def test_txt_success(self):
        proc = _make_processor()
        with patch.object(proc, 'load_document', return_value=(True, "x" * 200)), \
             patch.object(proc, 'chunk_text', return_value=["chunk1", "chunk2"]):
            ok, msg, result = proc._load_document_chunks('/f.txt', 'f.txt', '.txt', None)
        assert ok is True
        assert len(result) == 2

    def test_txt_load_fails(self):
        proc = _make_processor()
        with patch.object(proc, 'load_document', return_value=(False, "error")):
            ok, msg, result = proc._load_document_chunks('/f.txt', 'f.txt', '.txt', None)
        assert ok is False

    def test_txt_insufficient_content(self):
        proc = _make_processor()
        with patch.object(proc, 'load_document', return_value=(True, "   ")):
            ok, msg, result = proc._load_document_chunks('/f.txt', 'f.txt', '.txt', None)
        assert ok is False

    def test_txt_no_chunks(self):
        proc = _make_processor()
        with patch.object(proc, 'load_document', return_value=(True, "x" * 200)), \
             patch.object(proc, 'chunk_text', return_value=[]):
            ok, msg, result = proc._load_document_chunks('/f.txt', 'f.txt', '.txt', None)
        assert ok is False

    def test_progress_callback_called(self):
        proc = _make_processor()
        cb = MagicMock()
        with patch.object(proc, 'load_document', return_value=(True, "x" * 200)), \
             patch.object(proc, 'chunk_text', return_value=["c1"]):
            proc._load_document_chunks('/f.txt', 'f.txt', '.txt', cb)
        cb.assert_called()


# ---------------------------------------------------------------------------
# _build_embeddings_batch
# ---------------------------------------------------------------------------

class TestBuildEmbeddingsBatch:
    def test_successful_batch_returns_chunks_data(self):
        proc = _make_processor()
        chunks_meta = [
            {'text': 'chunk1', 'chunk_index': 0, 'page_number': 1, 'section_title': 'Intro'},
            {'text': 'chunk2', 'chunk_index': 1, 'page_number': 1, 'section_title': None},
        ]
        mock_bp = MagicMock()
        mock_bp.process_batch.return_value = [[0.1] * 768, [0.2] * 768]
        with patch('src.performance.batch_processor.BatchEmbeddingProcessor', return_value=mock_bp):
            result, failed = proc._build_embeddings_batch(
                chunks_meta, doc_id=1, embedding_model='nomic',
                filename='f.pdf', progress_callback=None
            )
        assert len(result) == 2
        assert failed == 0

    def test_failed_embeddings_counted(self):
        proc = _make_processor()
        chunks_meta = [
            {'text': 'c1', 'chunk_index': 0, 'page_number': None, 'section_title': None},
            {'text': 'c2', 'chunk_index': 1, 'page_number': None, 'section_title': None},
        ]
        mock_bp = MagicMock()
        mock_bp.process_batch.return_value = [None, [0.1] * 768]
        with patch('src.performance.batch_processor.BatchEmbeddingProcessor', return_value=mock_bp):
            result, failed = proc._build_embeddings_batch(
                chunks_meta, doc_id=1, embedding_model='nomic',
                filename='f.pdf', progress_callback=None
            )
        assert failed == 1
        assert len(result) == 1

    def test_progress_callback_called_on_milestone(self):
        proc = _make_processor()
        chunks_meta = [
            {'text': f'c{i}', 'chunk_index': i, 'page_number': None, 'section_title': None}
            for i in range(20)
        ]
        mock_bp = MagicMock()
        mock_bp.process_batch.return_value = [[float(i)] * 768 for i in range(20)]
        cb = MagicMock()
        with patch('src.performance.batch_processor.BatchEmbeddingProcessor', return_value=mock_bp):
            proc._build_embeddings_batch(
                chunks_meta, doc_id=1, embedding_model='nomic',
                filename='f.pdf', progress_callback=cb
            )
        cb.assert_called()


# ---------------------------------------------------------------------------
# process_document_chunk
# ---------------------------------------------------------------------------

class TestProcessDocumentChunk:
    def test_successful_chunk_returns_tuple(self):
        proc = _make_processor()
        with patch('src.rag.processor.ollama_client') as mock_client:
            mock_client.generate_embedding.return_value = (True, [0.1] * 768)
            result = proc.process_document_chunk(1, "some text", 0, "nomic")
        assert result is not None
        assert result[0] == 1

    def test_failed_embedding_returns_none(self):
        proc = _make_processor()
        with patch('src.rag.processor.ollama_client') as mock_client:
            mock_client.generate_embedding.return_value = (False, None)
            result = proc.process_document_chunk(1, "text", 0, "nomic")
        assert result is None


# ---------------------------------------------------------------------------
# generate_embeddings_batch
# ---------------------------------------------------------------------------

class TestGenerateEmbeddingsBatch:
    def test_no_model_returns_nones(self):
        proc = _make_processor()
        with patch('src.rag.processor.ollama_client') as mock_client:
            mock_client.get_embedding_model.return_value = None
            result = proc.generate_embeddings_batch(["t1", "t2"])
        assert result == [None, None]

    def test_with_explicit_model(self):
        proc = _make_processor()
        with patch('src.rag.processor.ollama_client') as mock_client:
            mock_client.generate_embedding.side_effect = [
                (True, [0.1] * 768), (True, [0.2] * 768)
            ]
            result = proc.generate_embeddings_batch(["t1", "t2"], model="nomic")
        assert len(result) == 2
        assert result[0] is not None


# ---------------------------------------------------------------------------
# chunk_pages_with_metadata
# ---------------------------------------------------------------------------

class TestChunkPagesWithMetadata:
    def test_basic_pages_produce_chunks(self):
        proc = _make_processor()
        pages = [
            {"page_number": 1, "text": "word " * 100, "section_title": "Intro"},
            {"page_number": 2, "text": "word " * 50, "section_title": None},
        ]
        chunks = proc.chunk_pages_with_metadata(pages)
        assert isinstance(chunks, list)
        for c in chunks:
            assert 'text' in c
            assert 'page_number' in c

    def test_empty_pages_returns_empty(self):
        proc = _make_processor()
        assert proc.chunk_pages_with_metadata([]) == []

    def test_short_page_text_skipped(self):
        proc = _make_processor()
        pages = [{"page_number": 1, "text": "short", "section_title": None}]
        chunks = proc.chunk_pages_with_metadata(pages)
        # Very short text shouldn't produce any chunks
        assert isinstance(chunks, list)
