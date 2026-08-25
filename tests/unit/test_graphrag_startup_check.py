"""GRAPH_RAG_ENABLED must not be able to look on while doing nothing.

Both halves of GraphRAG are best-effort: extraction never fails an ingest, and
expansion never fails a query. Without a spaCy model that combination leaves the
flag on, every ingest reporting success, and the feature inert — which is how the
DEL-2 comparison scored an identical +0.000 with expansion supposedly enabled.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src import app_bootstrap

pytestmark = [pytest.mark.unit]


class TestGraphRagStartupCheck:

    def test_says_nothing_when_the_feature_is_off(self, caplog):
        with patch.object(app_bootstrap.config, "GRAPH_RAG_ENABLED", False):
            app_bootstrap._check_graphrag()
        assert caplog.records == []

    def test_warns_when_enabled_without_a_model(self, caplog):
        with patch.object(app_bootstrap.config, "GRAPH_RAG_ENABLED", True), \
             patch("src.graph.extractor._get_nlp", return_value=None):
            app_bootstrap._check_graphrag()
        assert [r.levelname for r in caplog.records] == ["WARNING"]
        message = caplog.records[0].getMessage()
        assert "spacy download en_core_web_sm" in message
        assert "do nothing" in message

    def test_confirms_availability_when_a_model_loads(self, caplog):
        with patch.object(app_bootstrap.config, "GRAPH_RAG_ENABLED", True), \
             patch("src.graph.extractor._get_nlp", return_value=object()):
            app_bootstrap._check_graphrag()
        assert [r.levelname for r in caplog.records] == ["INFO"]

    def test_a_broken_check_does_not_stop_startup(self, caplog):
        with patch.object(app_bootstrap.config, "GRAPH_RAG_ENABLED", True), \
             patch("src.graph.extractor._get_nlp", side_effect=RuntimeError("boom")):
            app_bootstrap._check_graphrag()
        assert [r.levelname for r in caplog.records] == ["WARNING"]
        assert "non-fatal" in caplog.records[0].getMessage()
