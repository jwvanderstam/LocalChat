"""Coverage for built-in tools (search_documents, list_documents)."""

from unittest.mock import MagicMock, patch

import pytest


class TestSearchDocumentsTool:
    def test_no_results_returns_not_found_message(self):
        import src.tools.builtin  # ensure registered
        from src.tools.registry import tool_registry

        with patch('src.rag.doc_processor.retrieve_context', return_value=[]):
            result = tool_registry.execute("search_documents", {"query": "unknown topic"})

        assert "No relevant" in result

    def test_results_returned_as_formatted_context(self):
        import src.tools.builtin
        from src.tools.registry import tool_registry

        with patch('src.rag.doc_processor.retrieve_context',
                   return_value=[("chunk text", "doc.pdf", 0, 0.9, {})]), \
             patch('src.rag.doc_processor.format_context_for_llm',
                   return_value="Formatted chunk text"):
            result = tool_registry.execute("search_documents", {"query": "python"})

        assert "Formatted chunk text" in result

    def test_search_documents_is_registered(self):
        import src.tools.builtin
        from src.tools.registry import tool_registry
        assert tool_registry.get("search_documents") is not None


class TestListDocumentsTool:
    def test_no_documents_returns_message(self):
        import src.tools.builtin
        from src.tools.registry import tool_registry

        with patch('src.db.db.get_all_documents', return_value=[]):
            result = tool_registry.execute("list_documents", {})

        assert "No documents" in result

    def test_documents_listed_with_metadata(self):
        import src.tools.builtin
        from src.tools.registry import tool_registry

        docs = [
            {"filename": "report.pdf", "chunk_count": 10, "created_at": "2025-01-01"},
            {"filename": "notes.txt", "chunk_count": 3, "created_at": "2025-01-02"},
        ]
        with patch('src.db.db.get_all_documents', return_value=docs):
            result = tool_registry.execute("list_documents", {})

        assert "report.pdf" in result
        assert "notes.txt" in result
        assert "2 document" in result

    def test_db_error_returns_error_message(self):
        import src.tools.builtin
        from src.tools.registry import tool_registry

        with patch('src.db.db.get_all_documents', side_effect=Exception("DB down")):
            result = tool_registry.execute("list_documents", {})

        assert "Could not retrieve" in result

    def test_list_documents_is_registered(self):
        import src.tools.builtin
        from src.tools.registry import tool_registry
        assert tool_registry.get("list_documents") is not None


class TestCalculateToolEdgeCases:
    def test_power_operator(self):
        import src.tools.builtin
        from src.tools.registry import tool_registry
        result = tool_registry.execute("calculate", {"expression": "2 ** 8"})
        assert "256" in result

    def test_modulo_operator(self):
        import src.tools.builtin
        from src.tools.registry import tool_registry
        result = tool_registry.execute("calculate", {"expression": "10 % 3"})
        assert "1" in result

    def test_division(self):
        import src.tools.builtin
        from src.tools.registry import tool_registry
        result = tool_registry.execute("calculate", {"expression": "10 / 4"})
        assert "2.5" in result

    def test_invalid_expression_returns_error(self):
        import src.tools.builtin
        from src.tools.registry import tool_registry
        result = tool_registry.execute("calculate", {"expression": "import os"})
        assert "Invalid" in result or "error" in result.lower()

    def test_syntax_error_expression(self):
        import src.tools.builtin
        from src.tools.registry import tool_registry
        result = tool_registry.execute("calculate", {"expression": "1 + + + 2"})
        # Should either eval or return error - just no exception
        assert isinstance(result, str)
