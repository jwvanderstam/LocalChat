"""Unit tests for src/services/chat.py's pure-ish helper functions."""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


class TestApplyModelRouting:
    def test_user_override_short_circuits_router(self):
        from src.services.chat import apply_model_routing

        model, reason = apply_model_routing(
            {"model_override": "llama3", "message": "hi"}, "default-model", [], None
        )

        assert model == "llama3"
        assert reason == "user override"

    def test_router_disabled_returns_active_model(self):
        from src.services.chat import apply_model_routing

        with patch("src.services.chat.config.MODEL_ROUTER_ENABLED", False):
            model, reason = apply_model_routing({"message": "hi"}, "default-model", [], None)

        assert model == "default-model"
        assert reason is None

    def test_router_enabled_extracts_doc_types_from_sources(self):
        """Covers the doc_types walrus-filter comprehension: only sources with a
        truthy doc_type contribute, in source order."""
        from src.services.chat import apply_model_routing

        sources = [
            {"doc_type": "pdf"},
            {"doc_type": None},
            {"doc_type": "docx"},
            {},
        ]
        mock_router = MagicMock()
        mock_router.select.return_value = ("routed-model", "doc-type match")

        with patch("src.services.chat.config.MODEL_ROUTER_ENABLED", True), \
             patch("src.agent.router.ModelRouter", return_value=mock_router):
            model, reason = apply_model_routing(
                {"message": "hi"}, "default-model", sources, plan=None
            )

        assert model == "routed-model"
        assert reason == "doc-type match"
        _, kwargs = mock_router.select.call_args
        assert kwargs["doc_types"] == ["pdf", "docx"]

    def test_router_failure_falls_back_to_active_model(self):
        from src.services.chat import apply_model_routing

        with patch("src.services.chat.config.MODEL_ROUTER_ENABLED", True), \
             patch("src.agent.router.ModelRouter", side_effect=RuntimeError("boom")):
            model, reason = apply_model_routing(
                {"message": "hi"}, "default-model", [], plan=None
            )

        assert model == "default-model"
        assert reason is None


@pytest.mark.unit
class TestOllamaLivenessWorkerStops:
    """The liveness thread had no stop condition. It polled every 10 s for the
    life of the process, and `check_connection()` logs a traceback when Ollama is
    unreachable — so a test run that outlived the suite wrote to stderr while the
    interpreter was finalising, producing `_enter_buffered_busy` and exit 134
    after every test had passed. Found by naming the surviving threads at session
    end, not by reading the code: three earlier guesses were all wrong.
    """

    def _app_state(self):
        app_state = MagicMock()
        app_state.ollama_client.check_connection.return_value = (True, "ok")
        app_state.startup_status = {"database": True}
        return app_state

    def test_the_worker_thread_ends_when_asked(self):
        from src.services import chat

        chat.check_ollama_live(self._app_state())
        thread = chat._ollama_refresh_thread
        assert thread is not None and thread.is_alive()

        chat.stop_ollama_liveness(timeout=5.0)

        assert not thread.is_alive()

    def test_stopping_returns_promptly_rather_than_waiting_out_the_ttl(self):
        """`Event.wait` replaced `time.sleep` precisely so a stop is not held up
        by the remaining poll interval."""
        import time as _time

        from src.services import chat

        chat.check_ollama_live(self._app_state())
        started = _time.monotonic()
        chat.stop_ollama_liveness(timeout=5.0)

        assert _time.monotonic() - started < chat._OLLAMA_STATUS_TTL

    def test_stopping_when_nothing_runs_is_harmless(self):
        from src.services import chat

        chat.stop_ollama_liveness()
        chat.stop_ollama_liveness()

    def test_liveness_can_be_started_again_after_a_stop(self):
        """The stop event has to be cleared, or the app comes back up with a
        worker that exits on its first wait."""
        from src.services import chat

        chat.check_ollama_live(self._app_state())
        chat.stop_ollama_liveness(timeout=5.0)
        chat.check_ollama_live(self._app_state())
        try:
            assert chat._ollama_refresh_thread.is_alive()
        finally:
            chat.stop_ollama_liveness(timeout=5.0)
