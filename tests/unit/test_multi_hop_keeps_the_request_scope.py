"""A question the planner splits keeps every restriction the single-query path keeps.

ADR-6 recorded it as a live defect: `get_rag_context_multi_hop` took neither
`source_ids` nor `additional_workspace_ids`, so a chat narrowed to chosen sources searched
the whole workspace whenever the planner judged the question multi-hop, and a chat spanning
extra workspaces silently lost them. Its citations also lacked `knowledge_tier`, so a
global contribution in a multi-hop answer was cited as a workspace document (GKB-3).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src import config
from src.rag.planner import QueryPlan
from src.rag.retrieval import RetrievalResult
from src.services import chat

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _direct_retrieval(monkeypatch):
    # Either flag sends retrieval down another path before multi-hop is reached, and the
    # single-query control would then pass for the wrong reason.
    monkeypatch.setattr(config, "AGGREGATOR_AGENT_ENABLED", False)
    monkeypatch.setattr(config, "MCP_ENABLED", False)

WS = "11111111-1111-1111-1111-111111111111"
OTHER_WS = "22222222-2222-2222-2222-222222222222"


def _processor(results: list[RetrievalResult]) -> MagicMock:
    processor = MagicMock()
    processor.retrieve_context.return_value = results
    processor.format_context_for_llm.return_value = "context"
    return processor


def _result(chunk_id: int, tier: str = "local", low: bool = False) -> RetrievalResult:
    return RetrievalResult(
        chunk_text="text", filename=f"doc{chunk_id}.md", chunk_index=0,
        similarity=0.9 - chunk_id / 100,
        metadata={"knowledge_tier": tier, "low_relevance": low}, chunk_id=chunk_id,
    )


def _retrieve(processor: MagicMock, plan: QueryPlan, **kwargs: Any) -> list[dict[str, Any]]:
    fields = {"message": "a question", "use_rag": True, "enhance": False,
              "conversation_id": None, "knowledge_scope": kwargs.pop("knowledge_scope", "local")}
    db = MagicMock()
    db.conversations.document_filter.return_value = []
    _, _, sources, _ = chat.retrieve_contexts(
        fields, processor, db, [0], plan=plan, scope=WS, **kwargs,
    )
    return sources


MULTI_HOP = QueryPlan(sub_questions=["first part?", "second part?"], estimated_hops=2)


class TestEverySubQuestionKeepsTheRequestScope:
    def test_chosen_sources_reach_every_sub_question(self):
        processor = _processor([])
        _retrieve(processor, MULTI_HOP, source_ids=["src-1", "src-2"])
        assert [c.kwargs["source_ids"] for c in processor.retrieve_context.call_args_list] == [
            ["src-1", "src-2"], ["src-1", "src-2"],
        ]

    def test_additional_workspaces_reach_every_sub_question(self):
        processor = _processor([])
        _retrieve(processor, MULTI_HOP, additional_workspace_ids=[OTHER_WS])
        assert [c.kwargs["additional_workspace_ids"] for c in processor.retrieve_context.call_args_list] == [
            [OTHER_WS], [OTHER_WS],
        ]

    def test_without_either_the_sub_questions_search_the_workspace_alone(self):
        processor = _processor([])
        _retrieve(processor, MULTI_HOP)
        assert [
            (c.kwargs["source_ids"], c.kwargs["additional_workspace_ids"])
            for c in processor.retrieve_context.call_args_list
        ] == [([], None), ([], None)]

    def test_every_sub_question_gets_all_five_restrictions_of_the_request(self):
        processor = _processor([])
        db_filter = ["chosen.md"]
        fields = {"message": "a question", "use_rag": True, "enhance": False,
                  "conversation_id": "c1", "knowledge_scope": "hybrid"}
        db = MagicMock()
        db.conversations.document_filter.return_value = db_filter
        chat.retrieve_contexts(fields, processor, db, [0], plan=MULTI_HOP, scope=WS,
                               source_ids=["src-1"], additional_workspace_ids=[OTHER_WS])
        assert [
            {k: c.kwargs[k] for k in ("scope", "knowledge_scope", "filename_filter",
                                      "source_ids", "additional_workspace_ids")}
            for c in processor.retrieve_context.call_args_list
        ] == [{"scope": WS, "knowledge_scope": "hybrid", "filename_filter": db_filter,
               "source_ids": ["src-1"], "additional_workspace_ids": [OTHER_WS]}] * 2

    def test_the_single_query_path_still_passes_the_same_restriction(self):
        processor = _processor([])
        _retrieve(processor, QueryPlan(sub_questions=["one?"], estimated_hops=1),
                  source_ids=["src-1"], additional_workspace_ids=[OTHER_WS])
        call = processor.retrieve_context.call_args
        assert (call.kwargs["source_ids"], call.kwargs["additional_workspace_ids"]) == (
            ["src-1"], [OTHER_WS],
        )


class TestAMultiHopCitationSaysWhatItIs:
    def test_a_global_chunk_is_cited_as_global_and_a_workspace_one_as_local(self):
        processor = _processor([_result(1, tier="global"), _result(2, tier="local")])
        sources = _retrieve(processor, MULTI_HOP, knowledge_scope="hybrid")
        assert {s["chunk_id"]: s["knowledge_tier"] for s in sources} == {1: "global", 2: "local"}

    def test_a_weak_chunk_is_marked_low_relevance(self):
        processor = _processor([_result(1, low=True), _result(2, low=False)])
        sources = _retrieve(processor, MULTI_HOP)
        assert {s["chunk_id"]: s["low_relevance"] for s in sources} == {1: True, 2: False}
