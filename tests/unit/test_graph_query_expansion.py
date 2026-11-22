"""Retrieval's GraphRAG step: the query gains 1-hop terms when it is on, and is left alone otherwise.

The expansion is optional, so every way it can fail must hand back the query unchanged.
"""

from unittest.mock import patch

import pytest

from src.rag.retrieval import Retriever

pytestmark = pytest.mark.unit

_EXPANDER = "src.graph.expander.QueryExpander.expand"


def test_the_query_is_unchanged_when_graphrag_is_off():
    with patch("src.rag.retrieval.config.GRAPH_RAG_ENABLED", False), patch(_EXPANDER) as expand:
        result = Retriever._expand_with_graph("pump maintenance", "ws-1")

    assert result == "pump maintenance"
    expand.assert_not_called()


def test_the_expander_terms_are_appended_in_order():
    with patch("src.rag.retrieval.config.GRAPH_RAG_ENABLED", True), \
            patch(_EXPANDER, return_value=["Acme", "Rotterdam"]) as expand:
        result = Retriever._expand_with_graph("pump maintenance", "ws-1")

    assert result == "pump maintenance Acme Rotterdam"
    assert expand.call_args.kwargs["scope"] == "ws-1"


def test_no_terms_leave_the_query_unchanged():
    with patch("src.rag.retrieval.config.GRAPH_RAG_ENABLED", True), patch(_EXPANDER, return_value=[]):
        result = Retriever._expand_with_graph("pump maintenance", "ws-1")

    assert result == "pump maintenance"


def test_a_failing_expander_leaves_the_query_unchanged():
    with patch("src.rag.retrieval.config.GRAPH_RAG_ENABLED", True), \
            patch(_EXPANDER, side_effect=RuntimeError("spaCy model missing")):
        result = Retriever._expand_with_graph("pump maintenance", "ws-1")

    assert result == "pump maintenance"
