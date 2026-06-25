"""
Document Re-ingestion Dedup Tests
==================================

Unit tests for duplicate detection via SHA-256 file hash.

Scenarios tested:
- New document (no prior record) → ingested normally
- Same filename + same hash → skipped, existing doc_id returned
- Same filename + different hash → old doc deleted, re-ingested (replaced)
- _compute_file_hash produces consistent SHA-256 hex digest
"""

import hashlib
from unittest.mock import MagicMock, call, patch  # noqa: F401

import pytest

from src.rag.processor import _compute_file_hash

# ---------------------------------------------------------------------------
# _compute_file_hash
# ---------------------------------------------------------------------------

class TestComputeFileHash:
    def test_returns_sha256_hex(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_bytes(b"hello world")
        result = _compute_file_hash(str(f))
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert result == expected

    def test_different_content_gives_different_hash(self, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_bytes(b"content A")
        b.write_bytes(b"content B")
        assert _compute_file_hash(str(a)) != _compute_file_hash(str(b))

    def test_same_content_gives_same_hash(self, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_bytes(b"identical")
        b.write_bytes(b"identical")
        assert _compute_file_hash(str(a)) == _compute_file_hash(str(b))

    def test_large_file_processed_in_blocks(self, tmp_path):
        """Verify files larger than the 64 KiB block still hash correctly."""
        data = b"x" * (200 * 1024)  # 200 KiB
        f = tmp_path / "large.bin"
        f.write_bytes(data)
        result = _compute_file_hash(str(f))
        assert result == hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# ingest_document dedup logic
# ---------------------------------------------------------------------------

@pytest.fixture()
def processor():
    """Return a DocumentProcessor with all heavy dependencies mocked."""
    from unittest.mock import MagicMock

    from src.rag.processor import DocumentProcessor

    return DocumentProcessor(db=MagicMock(), ollama_client=MagicMock())


@pytest.fixture()
def txt_file(tmp_path):
    f = tmp_path / "report.txt"
    f.write_text("Some document content for testing.", encoding="utf-8")
    return str(f)


FILE_HASH = hashlib.sha256(b"Some document content for testing.").hexdigest()


class TestIngestDocumentDedup:
    """DocumentProcessor with injected mocks — no real services needed."""

    def test_new_document_is_ingested(self, processor, txt_file):
        mock_db = processor._db
        mock_ollama = processor._ollama_client
        mock_db.document_exists.return_value = (False, {})
        mock_db.insert_document.return_value = 42
        mock_ollama.get_embedding_model.return_value = "nomic-embed-text"

        with (
            patch("src.rag.processor._compute_file_hash", return_value=FILE_HASH),
            patch.object(processor, "_load_document_chunks",
                         return_value=(True, None, [{"text": "chunk", "metadata": {}}], "content", "TXT", "text-v1")),
            patch.object(processor, "_run_embedding_pipeline",
                         return_value=([{"chunk_text": "chunk"}], 0)),
        ):
            success, msg, doc_id = processor.ingest_document(txt_file)

        assert success is True
        assert doc_id == 42
        mock_db.delete_document.assert_not_called()
        mock_db.insert_document.assert_called_once()
        _, kwargs = mock_db.insert_document.call_args
        assert kwargs.get("content_hash") == FILE_HASH

    def test_same_hash_skips_ingestion(self, processor, txt_file):
        mock_db = processor._db
        mock_db.document_exists.return_value = (
            True,
            {"id": 7, "chunk_count": 5, "content_hash": FILE_HASH},
        )

        with patch("src.rag.processor._compute_file_hash", return_value=FILE_HASH):
            success, msg, doc_id = processor.ingest_document(txt_file)

        assert success is True
        assert doc_id == 7
        assert "up to date" in msg
        mock_db.delete_document.assert_not_called()
        mock_db.insert_document.assert_not_called()

    def test_different_hash_replaces_document(self, processor, txt_file):
        old_hash = "a" * 64
        mock_db = processor._db
        mock_ollama = processor._ollama_client
        mock_db.document_exists.return_value = (
            True,
            {"id": 3, "chunk_count": 10, "content_hash": old_hash},
        )
        mock_db.insert_document.return_value = 99
        mock_ollama.get_embedding_model.return_value = "nomic-embed-text"

        with (
            patch("src.rag.processor._compute_file_hash", return_value=FILE_HASH),
            patch.object(processor, "_load_document_chunks",
                         return_value=(True, None, [{"text": "chunk", "metadata": {}}], "content", "TXT", "text-v1")),
            patch.object(processor, "_run_embedding_pipeline",
                         return_value=([{"chunk_text": "chunk"}], 0)),
        ):
            success, msg, doc_id = processor.ingest_document(txt_file)

        assert success is True
        assert doc_id == 99
        mock_db.delete_document.assert_called_once_with(3)
        mock_db.insert_document.assert_called_once()

    def test_replace_progress_callback_called(self, processor, txt_file):
        old_hash = "b" * 64
        progress_calls = []
        mock_db = processor._db
        mock_ollama = processor._ollama_client
        mock_db.document_exists.return_value = (
            True, {"id": 1, "chunk_count": 2, "content_hash": old_hash}
        )
        mock_db.insert_document.return_value = 10
        mock_ollama.get_embedding_model.return_value = "nomic-embed-text"

        with (
            patch("src.rag.processor._compute_file_hash", return_value=FILE_HASH),
            patch.object(processor, "_load_document_chunks",
                         return_value=(True, None, [{"text": "c", "metadata": {}}], "c", "TXT", "text-v1")),
            patch.object(processor, "_run_embedding_pipeline",
                         return_value=([{"chunk_text": "c"}], 0)),
        ):
            processor.ingest_document(txt_file, progress_callback=progress_calls.append)

        assert any("Replacing" in m for m in progress_calls)
