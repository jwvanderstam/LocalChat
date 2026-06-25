"""Integration tests for the full RAG pipeline: retrieve context → chat with LLM."""

import json
from unittest.mock import patch

import pytest

from src.rag.retrieval import RetrievalResult

SAMPLE_CHUNKS = [
    RetrievalResult(
        chunk_text="LocalChat supports pgvector for semantic similarity search.",
        filename="localchat_overview.txt",
        chunk_index=0,
        similarity=0.92,
        metadata={"page_number": None, "section_title": "Overview"},
        chunk_id=1,
    ),
    RetrievalResult(
        chunk_text="Documents are split into overlapping chunks and embedded with nomic-embed-text.",
        filename="localchat_overview.txt",
        chunk_index=1,
        similarity=0.88,
        metadata={"page_number": None, "section_title": "Overview"},
        chunk_id=2,
    ),
]

FORMATTED_CONTEXT = (
    "LocalChat supports pgvector for semantic similarity search. "
    "Documents are split into overlapping chunks and embedded with nomic-embed-text."
)


@pytest.mark.integration
class TestRagFlow:
    """Full RAG pipeline exercised through the /api/chat endpoint."""

    def setup_method(self):
        from src import config

        self._original_model = config.app_state.get_active_model()

    def teardown_method(self):
        from src import config

        config.app_state.set_active_model(self._original_model)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _rag_chat(self, client, app, message: str = "What vector DB does LocalChat use?"):
        """POST /api/chat with RAG enabled and mocked services."""
        from src import config

        config.app_state.set_active_model("llama3.2")
        app.state.startup_status["ollama"] = True

        async def _gen_rag(*a, **k):
            yield "pgvector is used for semantic search."

        with (
            patch.object(app.state.doc_processor, "retrieve_context", return_value=SAMPLE_CHUNKS),
            patch.object(
                app.state.doc_processor,
                "format_context_for_llm",
                return_value=FORMATTED_CONTEXT,
            ),
            patch.object(
                app.state.ollama_client,
                "generate_chat_response",
                side_effect=_gen_rag,
            ),
        ):
            return client.post("/api/chat", json={"message": message, "use_rag": True})

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_rag_chat_returns_200_sse_stream(self, app, client):
        resp = self._rag_chat(client, app)
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers['content-type']

    def test_rag_chat_stream_contains_llm_content(self, app, client):
        resp = self._rag_chat(client, app)
        assert "pgvector is used for semantic search." in resp.content.decode()

    def test_rag_stream_ends_with_done_event(self, app, client):
        resp = self._rag_chat(client, app)
        body = resp.content.decode()
        data_lines = [ln for ln in body.splitlines() if ln.startswith("data:")]
        assert data_lines, "Expected at least one SSE data line"
        last = json.loads(data_lines[-1].removeprefix("data:").strip())
        assert last.get("done") is True

    def test_retrieve_context_is_called_with_user_message(self, app, client):
        from src import config

        config.app_state.set_active_model("llama3.2")
        app.state.startup_status["ollama"] = True

        async def _gen_ok(*a, **k):
            yield "ok"

        with (
            patch.object(
                app.state.doc_processor, "retrieve_context", return_value=SAMPLE_CHUNKS
            ) as mock_retrieve,
            patch.object(
                app.state.doc_processor,
                "format_context_for_llm",
                return_value=FORMATTED_CONTEXT,
            ),
            patch.object(
                app.state.ollama_client,
                "generate_chat_response",
                side_effect=_gen_ok,
            ),
        ):
            client.post(
                "/api/chat",
                json={"message": "Tell me about pgvector", "use_rag": True},
            )

        mock_retrieve.assert_called_once_with(
            "Tell me about pgvector",
            filename_filter=[],
            workspace_id=None,
            additional_workspace_ids=None,
            source_ids=[],
        )

    def test_context_text_forwarded_to_llm(self, app, client):
        """The formatted context must appear in the messages sent to the LLM."""
        from src import config

        config.app_state.set_active_model("llama3.2")
        app.state.startup_status["ollama"] = True
        captured: list = []

        async def capture_generate(model, messages, **kwargs):
            captured.extend(messages)
            yield "answer"

        with (
            patch.object(app.state.doc_processor, "retrieve_context", return_value=SAMPLE_CHUNKS),
            patch.object(
                app.state.doc_processor,
                "format_context_for_llm",
                return_value=FORMATTED_CONTEXT,
            ),
            patch.object(
                app.state.ollama_client,
                "generate_chat_response",
                side_effect=capture_generate,
            ),
        ):
            client.post(
                "/api/chat",
                json={"message": "Tell me about pgvector", "use_rag": True},
            )

        all_content = " ".join(
            m.get("content", "") for m in captured if isinstance(m, dict)
        )
        assert "pgvector" in all_content

    def test_use_rag_false_skips_retrieval(self, app, client):
        """use_rag=False must not call retrieve_context at all."""
        from src import config

        config.app_state.set_active_model("llama3.2")
        app.state.startup_status["ollama"] = True

        with (
            patch.object(app.state.doc_processor, "retrieve_context") as mock_retrieve,
            patch.object(
                app.state.ollama_client,
                "generate_chat_response",
                return_value=iter(["direct answer"]),
            ),
            # When no RAG context is present, _get_tool_executor creates a ToolExecutor
            # which calls generate_chat_completion (not generate_chat_response). Without
            # this mock the executor may invoke the search_documents built-in tool, which
            # calls retrieve_context through the module-level singleton.
            patch.object(
                app.state.ollama_client,
                "generate_chat_completion",
                return_value={"message": {"role": "assistant", "content": "direct answer"}},
            ),
        ):
            client.post("/api/chat", json={"message": "hello", "use_rag": False})

        mock_retrieve.assert_not_called()

    def test_no_active_model_returns_400(self, app, client):
        from src import config

        config.app_state.set_active_model(None)

        resp = client.post("/api/chat", json={"message": "hi", "use_rag": True})
        assert resp.status_code == 400

    def test_document_upload_endpoint_accepts_txt_file(self, app, client, tmp_path):
        """POST /api/documents should stream progress for a valid .txt file."""
        txt_file = tmp_path / "test_doc.txt"
        txt_file.write_text(FORMATTED_CONTEXT)

        with (
            patch.object(
                app.state.doc_processor,
                "ingest_document",
                return_value=(True, "Ingested 2 chunks", 1),
            ),
            patch(
                "src.routes_fastapi.document_routes._save_upload_file",
                return_value=str(txt_file),
            ),
        ):
            with txt_file.open("rb") as fh:
                resp = client.post(
                    "/api/documents/upload",
                    files=[("files", ("test_doc.txt", fh, "text/plain"))],
                )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers['content-type']
