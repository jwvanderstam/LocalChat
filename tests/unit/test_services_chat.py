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
