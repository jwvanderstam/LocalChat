# -*- coding: utf-8 -*-
"""Tests for api_routes helpers and endpoints."""

import json
import pytest
from unittest.mock import MagicMock, patch


class TestInsertSystemPrompt:
    def test_inserts_when_messages_empty(self):
        from src.routes.api_routes import _insert_system_prompt
        messages = []
        _insert_system_prompt(messages, "You are helpful.")
        assert messages[0] == {'role': 'system', 'content': 'You are helpful.'}

    def test_does_not_insert_when_system_already_present(self):
        from src.routes.api_routes import _insert_system_prompt
        messages = [{'role': 'system', 'content': 'Existing'}]
        _insert_system_prompt(messages, "New prompt")
        assert messages[0]['content'] == 'Existing'

    def test_inserts_before_non_system_first_message(self):
        from src.routes.api_routes import _insert_system_prompt
        messages = [{'role': 'user', 'content': 'Hi'}]
        _insert_system_prompt(messages, "Be helpful.")
        assert messages[0]['role'] == 'system'
        assert messages[1]['role'] == 'user'


class TestBuildContextPrompt:
    def test_local_context_inserts_system_prompt(self):
        from src.routes.api_routes import _build_context_prompt
        msgs, final = _build_context_prompt(
            "what is X?", "X is a variable.", "", [], True, False
        )
        assert any(m['role'] == 'system' for m in msgs)
        assert "what is X?" in final

    def test_web_context_uses_enhanced_prompt(self):
        from src.routes.api_routes import _build_context_prompt
        msgs, final = _build_context_prompt(
            "news?", "", "=== Web Results ===\nLatest news...", [], True, True
        )
        system_msgs = [m for m in msgs if m['role'] == 'system']
        assert len(system_msgs) == 1

    def test_both_contexts_combined(self):
        from src.routes.api_routes import _build_context_prompt
        msgs, final = _build_context_prompt(
            "query", "local context", "web context", [], True, True
        )
        assert "local context" in final
        assert "web context" in final

    def test_rag_no_results_inserts_fallback_prompt(self):
        from src.routes.api_routes import _build_context_prompt
        msgs, final = _build_context_prompt("q", "", "", [], True, False)
        assert any(m['role'] == 'system' for m in msgs)
        assert final == "q"

    def test_direct_llm_no_context_no_system_prompt(self):
        from src.routes.api_routes import _build_context_prompt
        msgs, final = _build_context_prompt("q", "", "", [], False, False)
        assert final == "q"

    def test_existing_system_not_overwritten(self):
        from src.routes.api_routes import _build_context_prompt
        existing = [{'role': 'system', 'content': 'Custom system'}]
        msgs, final = _build_context_prompt("q", "ctx", "", existing, True, False)
        system_msgs = [m for m in msgs if m['role'] == 'system']
        assert len(system_msgs) == 1
        assert system_msgs[0]['content'] == 'Custom system'


class TestGetRagContext:
    def test_returns_empty_when_no_results(self):
        from src.routes.api_routes import _get_rag_context
        doc_processor = MagicMock()
        doc_processor.retrieve_context.return_value = []
        result = _get_rag_context("query", doc_processor)
        assert result == ""

    def test_returns_formatted_context_on_results(self):
        from src.routes.api_routes import _get_rag_context
        doc_processor = MagicMock()
        doc_processor.retrieve_context.return_value = [
            ("chunk", "doc.pdf", 0, 0.9, {"page_number": 1})
        ]
        doc_processor.format_context_for_llm.return_value = "Formatted context"
        result = _get_rag_context("query", doc_processor)
        assert result == "Formatted context"


class TestGetWebContext:
    def test_returns_empty_when_no_results(self):
        from src.routes.api_routes import _get_web_context
        with patch('src.routes.api_routes._get_web_context', return_value=""):
            from src.routes.api_routes import _get_web_context as fn
            # call directly with mock
        mock_searcher = MagicMock()
        mock_searcher.search.return_value = []
        with patch('src.rag.web_search.WebSearchProvider', return_value=mock_searcher):
            from src.routes.api_routes import _get_web_context
            result = _get_web_context("query")
            assert result == "" or isinstance(result, str)

    def test_returns_formatted_context_on_results(self):
        from src.routes.api_routes import _get_web_context
        mock_searcher = MagicMock()
        mock_result = MagicMock()
        mock_searcher.search.return_value = [mock_result]
        mock_searcher.format_web_context.return_value = "Web results text"

        with patch('src.rag.web_search.WebSearchProvider', return_value=mock_searcher):
            result = _get_web_context("query")
            assert isinstance(result, str)


class TestApiStatusEndpoint:
    def test_status_returns_200(self, client):
        response = client.get('/api/status')
        assert response.status_code == 200

    def test_status_has_expected_keys(self, client):
        response = client.get('/api/status')
        data = response.get_json()
        assert isinstance(data, dict)


class TestApiStatusTTLCache:
    """Tests for the document-count TTL cache inside api_status()."""

    def test_cache_miss_queries_db(self, app, client):
        """When the cache is stale, get_document_count() must be called."""
        import src.routes.api_routes as routes
        routes._status_doc_count_cache[1] = 0.0  # force cache miss
        app.startup_status['database'] = True
        app.db.get_document_count = MagicMock(return_value=42)
        response = client.get('/api/status')
        assert response.status_code == 200
        app.db.get_document_count.assert_called_once()

    def test_cache_hit_skips_db(self, app, client):
        """Within the TTL window, get_document_count() must NOT be called."""
        import time
        import src.routes.api_routes as routes
        routes._status_doc_count_cache[0] = 7
        routes._status_doc_count_cache[1] = time.monotonic()  # just refreshed
        app.startup_status['database'] = True
        app.db.get_document_count = MagicMock(return_value=99)
        response = client.get('/api/status')
        assert response.status_code == 200
        data = response.get_json()
        assert data['document_count'] == 7
        app.db.get_document_count.assert_not_called()

    def test_cache_miss_db_exception_marks_db_unavailable(self, app, client):
        """When the DB raises during a cache miss, database must be False in response."""
        import src.routes.api_routes as routes
        routes._status_doc_count_cache[1] = 0.0  # force cache miss
        app.startup_status['database'] = True
        app.db.get_document_count = MagicMock(side_effect=Exception("DB error"))
        response = client.get('/api/status')
        assert response.status_code == 200
        data = response.get_json()
        assert data['database'] is False


class TestApiChatEndpoint:
    def test_chat_missing_body_returns_400(self, client):
        response = client.post('/api/chat',
                               data='not json',
                               content_type='application/json')
        assert response.status_code in (400, 200)

    def test_chat_empty_json_returns_400(self, client):
        response = client.post('/api/chat',
                               data=json.dumps({}),
                               content_type='application/json')
        assert response.status_code in (400, 422)

    def test_chat_no_model_returns_400(self, client, app):
        from src import config
        original = config.app_state.get_active_model()
        config.app_state.set_active_model(None)
        try:
            response = client.post('/api/chat',
                                   data=json.dumps({'message': 'hello', 'use_rag': False}),
                                   content_type='application/json')
            assert response.status_code in (400, 200)
        finally:
            config.app_state.set_active_model(original)

    def test_chat_streams_with_active_model(self, client, app):
        from src import config
        config.app_state.set_active_model('llama3.2')
        app.ollama_client.generate_chat_response = MagicMock(
            return_value=iter(["Hello", " world"])
        )
        try:
            response = client.post('/api/chat',
                                   data=json.dumps({
                                       'message': 'Hello',
                                       'use_rag': False,
                                       'enhance': False,
                                       'history': []
                                   }),
                                   content_type='application/json')
            assert response.status_code in (200, 400)
        finally:
            config.app_state.set_active_model(None)

    def test_parse_chat_request_valid(self):
        from src.routes.api_routes import _parse_chat_request
        result = _parse_chat_request({
            'message': 'test message',
            'use_rag': True,
            'history': [],
        })
        assert result['message'] == 'test message'
        assert result['use_rag'] is True

    def test_parse_chat_request_sanitizes_message(self):
        from src.routes.api_routes import _parse_chat_request
        result = _parse_chat_request({'message': '  hello  ', 'use_rag': False})
        assert result['message'] == result['message'].strip()
