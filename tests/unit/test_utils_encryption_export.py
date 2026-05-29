"""Unit tests for src/utils/encryption.py, src/utils/export.py, src/rag/active_learning.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEncryption:
    def test_encrypt_none_returns_none(self):
        from src.utils.encryption import encrypt

        assert encrypt(None) is None

    def test_encrypt_empty_returns_empty(self):
        from src.utils.encryption import encrypt

        assert encrypt("") == ""

    def test_encrypt_no_key_returns_plaintext(self):
        from src.utils.encryption import encrypt

        with patch("src.utils.encryption._get_fernet", return_value=None):
            result = encrypt("hello world")
        assert result == "hello world"

    def test_decrypt_none_returns_none(self):
        from src.utils.encryption import decrypt

        assert decrypt(None) is None

    def test_decrypt_empty_returns_empty(self):
        from src.utils.encryption import decrypt

        assert decrypt("") == ""

    def test_decrypt_no_key_returns_plaintext(self):
        from src.utils.encryption import decrypt

        with patch("src.utils.encryption._get_fernet", return_value=None):
            result = decrypt("some ciphertext")
        assert result == "some ciphertext"

    def test_encrypt_decrypt_roundtrip_with_key(self):
        from cryptography.fernet import Fernet

        from src.utils.encryption import decrypt, encrypt

        key = Fernet.generate_key()
        fernet = Fernet(key)
        with patch("src.utils.encryption._get_fernet", return_value=fernet):
            ciphertext = encrypt("secret message")
            assert ciphertext != "secret message"
            plaintext = decrypt(ciphertext)
        assert plaintext == "secret message"

    def test_decrypt_unencrypted_value_with_key_falls_back(self):
        """Decrypt returns the raw value when it was stored before encryption was enabled."""
        from cryptography.fernet import Fernet

        from src.utils.encryption import decrypt

        key = Fernet.generate_key()
        fernet = Fernet(key)
        with patch("src.utils.encryption._get_fernet", return_value=fernet):
            result = decrypt("plain-text-never-encrypted")
        # Fallback: returns original text unchanged
        assert result == "plain-text-never-encrypted"

    def test_get_fernet_no_key_returns_none(self):
        from src.utils.encryption import _get_fernet

        with patch("src.config.ENCRYPTION_KEY", ""):
            result = _get_fernet()
        assert result is None

    def test_get_fernet_invalid_key_returns_none(self):
        from src.utils.encryption import _get_fernet

        with patch("src.config.ENCRYPTION_KEY", "not-a-valid-fernet-key"):
            result = _get_fernet()
        assert result is None


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestExportDocx:
    def test_export_empty_conversation(self):
        from src.utils.export import export_conversation_docx

        result = export_conversation_docx("Empty Chat", [])
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_export_with_messages(self):
        from src.utils.export import export_conversation_docx

        messages = [
            {"role": "user", "content": "What is the revenue?", "timestamp": "2026-01-01 10:00"},
            {"role": "assistant", "content": "The revenue is $1M.", "timestamp": "2026-01-01 10:01"},
        ]
        result = export_conversation_docx("Q1 Review", messages)
        assert isinstance(result, bytes)
        assert len(result) > 100

    def test_export_pdf_missing_reportlab(self):
        from src.utils.export import export_conversation_pdf

        with patch.dict("sys.modules", {"reportlab": None, "reportlab.lib": None}):
            with pytest.raises(ImportError, match="reportlab"):
                export_conversation_pdf("Chat", [])


# ---------------------------------------------------------------------------
# Active learning
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestActiveLearning:
    def test_suggest_documents_db_error_returns_empty(self):
        from src.rag.active_learning import suggest_documents

        db = MagicMock()
        db.get_low_confidence_queries.side_effect = RuntimeError("DB down")
        result = suggest_documents(workspace_id="ws-1", db=db)
        assert result == []

    def test_suggest_documents_no_queries_returns_empty(self):
        from src.rag.active_learning import suggest_documents

        db = MagicMock()
        db.get_low_confidence_queries.return_value = []
        result = suggest_documents(workspace_id="ws-1", db=db)
        assert result == []

    def test_suggest_documents_returns_top_terms(self):
        from src.rag.active_learning import suggest_documents

        db = MagicMock()
        db.get_low_confidence_queries.return_value = [
            "what is the revenue forecast",
            "explain the revenue growth",
            "revenue breakdown by region",
            "quarterly forecast report",
        ]
        result = suggest_documents(workspace_id=None, db=db)
        assert isinstance(result, list)
        assert len(result) > 0
        # "revenue" and "forecast" should appear frequently
        assert "revenue" in result

    def test_suggest_documents_top_k_limit(self):
        from src.rag.active_learning import suggest_documents

        db = MagicMock()
        db.get_low_confidence_queries.return_value = [
            f"what about {i} topic" for i in range(50)
        ]
        result = suggest_documents(workspace_id=None, db=db, top_k=3)
        assert len(result) <= 3

    def test_extract_terms_filters_stop_words(self):
        from src.rag.active_learning import _extract_terms

        terms = _extract_terms("what is the revenue growth for this quarter")
        assert "what" not in terms
        assert "the" not in terms
        assert "is" not in terms
        assert "for" not in terms
        assert "revenue" in terms
        assert "growth" in terms
        assert "quarter" in terms

    def test_extract_terms_excludes_short_words(self):
        from src.rag.active_learning import _extract_terms

        terms = _extract_terms("an is a to of or")
        assert terms == []
