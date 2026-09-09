"""An embedding model must never become the active chat model.

`get_first_available_model()` filters embedding families out of the candidate
list and then — this was the defect — fell back to the *unfiltered* list when
the filter left nothing, on the reasoning that some answer beats no answer.

It does not. Phase 4 of the Scaleway deployment pulls `nomic-embed-text` and
deliberately nothing else, so the fallback was guaranteed to fire on exactly
the stack those scripts build. The active model became the embedding model,
`/api/status` reported `ready: true`, upload and retrieval worked, and every
chat request came back as five opaque words:

    {"error": "GenerationError", "message": "Failed to generate response"}

The cause appeared in one place only, the log:

    Ollama API error 400: "nomic-embed-text:latest" does not support chat

Returning `None` instead routes the caller into the path `api_chat` already
has for this case — a 400 `NoModelConfigured` naming the remedy — rather than
into a generation failure that names nothing.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from src.ollama_client import OllamaClient

pytestmark = pytest.mark.unit


def _client_listing(*names: str) -> OllamaClient:
    """An OllamaClient whose `/api/tags` reports exactly *names*, in order."""
    client = OllamaClient(base_url="http://localhost:11434")
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "models": [{"name": n, "size": 1} for n in names]
    }
    client._session.get = Mock(return_value=response)
    return client


def test_returns_none_when_only_embedding_models_are_installed():
    client = _client_listing("nomic-embed-text:latest")

    assert client.get_first_available_model() is None


def test_returns_none_when_every_embedding_family_is_installed():
    """Each family the filter names, together — none of them is a chat model."""
    client = _client_listing(
        "nomic-embed-text:latest",
        "mxbai-embed-large:latest",
        "all-minilm:l6-v2",
        "embeddinggemma:300m",
    )

    assert client.get_first_available_model() is None


def test_prefers_the_chat_model_when_an_embedding_model_is_listed_first():
    """Ollama orders by modification time, and Phase 4 pulls the embedder last.

    The chat model is therefore *not* first in the list on a real stack, which
    is the ordering that matters: taking `models[0]` would return the embedder.
    """
    client = _client_listing("nomic-embed-text:latest", "llama3.2:1b")

    assert client.get_first_available_model() == "llama3.2:1b"


def test_preferred_model_does_not_resurrect_an_embedding_model():
    """A `DEFAULT_MODEL` naming an embedder must not smuggle it past the filter."""
    client = _client_listing("nomic-embed-text:latest")

    assert client.get_first_available_model(preferred="nomic-embed-text") is None


def test_startup_leaves_the_active_model_unset_when_nothing_can_chat():
    """The 400 `api_chat` returns for an unset model is the intended outcome.

    It names the problem and the remedy; a generation failure names neither.
    """
    from src.app_bootstrap import _init_ollama_service

    app = MagicMock()
    app.state.startup_status = {}
    ollama_client = MagicMock()
    ollama_client.check_connection.return_value = (True, "Connected")
    ollama_client.get_first_available_model.return_value = None

    with patch("src.app_bootstrap.config") as mock_config:
        mock_config.app_state.get_active_model.return_value = None
        with patch("src.app_bootstrap._warmup_embedding_model"), \
             patch("src.app_bootstrap._warmup_reranker"):
            _init_ollama_service(app, ollama_client)

    mock_config.app_state.set_active_model.assert_not_called()


def test_warns_that_chat_is_unavailable_rather_than_failing_silently():
    """Returning None is only half the fix — the operator has to learn why.

    Without this the symptom moves from an opaque generation error to an
    equally opaque 400, with nothing in the log connecting either to the
    missing model.
    """
    client = _client_listing("nomic-embed-text:latest")

    with patch("src.ollama_client.logger") as mock_logger:
        client.get_first_available_model()

    warnings = " ".join(str(c) for c in mock_logger.warning.call_args_list)
    assert "chat" in warnings.lower()


# ===========================================================================
# `/api/status` must not claim readiness it cannot deliver
# ===========================================================================


def _status_payload(active_model):
    """`GET /api/status` with *active_model*, everything else healthy."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.routes_fastapi.api_routes import router
    from tests.utils.auth import auth_headers, authorise_db

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.startup_status = {"database": True, "ollama": True, "ready": True}
    app.state.db = authorise_db(MagicMock())
    app.state.doc_processor = MagicMock()
    app.state.ollama_client = MagicMock()
    app.state.embedding_cache = None
    app.state.query_cache = None
    client = TestClient(app, raise_server_exceptions=True)

    with (
        patch("src.services.chat.get_doc_count_cached", return_value=(5, True)),
        patch("src.services.chat.check_ollama_live", return_value=True),
        patch("src.routes_fastapi.api_routes.config") as cfg,
    ):
        cfg.app_state.get_active_model.return_value = active_model
        cfg.MCP_ENABLED = False
        cfg.MODEL_ROUTER_ENABLED = False
        cfg.AGGREGATOR_AGENT_ENABLED = False
        cfg.GRAPH_RAG_ENABLED = False
        cfg.LONG_TERM_MEMORY_ENABLED = False
        return client.get("/api/status", headers=auth_headers()).json()


def test_status_is_not_ready_when_no_model_is_active():
    """Ollama and the database up is not enough — chat is what `ready` promises."""
    assert _status_payload(None)["ready"] is False


def test_status_is_ready_when_a_chat_model_is_active():
    """The other side of the boundary: nothing else changed, so ready holds."""
    assert _status_payload("llama3.2:1b")["ready"] is True


def test_status_names_the_missing_piece_rather_than_only_refusing():
    """A false `ready` has to be diagnosable from the same payload."""
    assert _status_payload(None)["active_model"] is None
