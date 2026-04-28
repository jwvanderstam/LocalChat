"""
Tests for src/agent/ — AggregatorAgent, ToolRouter, AgentResult, ToolCall.

Covers:
  - AgentResult / ToolCall serialisation
  - AggregatorAgent._dedup_sources
  - AggregatorAgent._resolve_tools / _resolve_queries
  - AggregatorAgent.run() — happy path, multi-tool parallel, partial failure,
    all-fail, multi-hop sub-questions, retry on transient error
  - ToolRouter.dispatch() — unknown tool, direct paths, MCP paths, MCP fallback
"""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------

def _make_tool_call(tool="local_docs", query="q", success=True, result_count=3,
                    latency_ms=42.0, error=None):
    from src.agent.result import ToolCall
    return ToolCall(
        tool=tool, query=query, success=success,
        result_count=result_count, latency_ms=latency_ms, error=error,
    )


def _make_plan(tools=None, sub_questions=None, estimated_hops=1):
    """Build a minimal QueryPlan-like object."""
    from src.rag.planner import QueryPlan
    return QueryPlan(
        intent="factual_lookup",
        sub_questions=sub_questions or [],
        tools=tools or ["local_docs"],
        synthesis_required=False,
        estimated_hops=estimated_hops,
    )


def _make_router(return_map: dict):
    """
    Build a ToolRouter mock whose dispatch() returns from return_map.
    Keys are tool names; values are the dict to return.
    Raises RuntimeError if key is "FAIL".
    """
    router = MagicMock()
    def _dispatch(tool_name, query, filters, top_k):
        val = return_map.get(tool_name, {"context": "", "sources": []})
        if val == "FAIL":
            raise RuntimeError(f"Simulated failure for {tool_name}")
        return val
    router.dispatch.side_effect = _dispatch
    return router


# ===========================================================================
# ToolCall
# ===========================================================================

class TestToolCall:
    def test_to_dict_happy(self):
        from src.agent.result import ToolCall
        tc = ToolCall(tool="local_docs", query="hello world", success=True,
                      result_count=5, latency_ms=123.456)
        d = tc.to_dict()
        assert d["tool"] == "local_docs"
        assert d["success"] is True
        assert d["result_count"] == 5
        assert d["latency_ms"] == 123.5  # rounded to 1 dp
        assert d["error"] is None

    def test_to_dict_query_truncated_at_100(self):
        from src.agent.result import ToolCall
        long_q = "x" * 200
        d = ToolCall(tool="t", query=long_q, success=True).to_dict()
        assert len(d["query"]) == 100

    def test_to_dict_failure(self):
        from src.agent.result import ToolCall
        tc = ToolCall(tool="web_search", query="q", success=False,
                      error="Connection refused")
        d = tc.to_dict()
        assert d["success"] is False
        assert d["error"] == "Connection refused"


# ===========================================================================
# AgentResult
# ===========================================================================

class TestAgentResult:
    def test_to_trace_dict_empty(self):
        from src.agent.result import AgentResult
        r = AgentResult(context="", contexts_by_tool={}, sources=[], tool_trace=[])
        assert r.to_trace_dict() == []

    def test_to_trace_dict_multiple(self):
        from src.agent.result import AgentResult
        trace = [
            _make_tool_call("local_docs", "q1", True, 3),
            _make_tool_call("web_search", "q1", False, 0, error="timeout"),
        ]
        r = AgentResult(context="ctx", contexts_by_tool={}, sources=[], tool_trace=trace)
        td = r.to_trace_dict()
        assert len(td) == 2
        assert td[0]["tool"] == "local_docs"
        assert td[1]["success"] is False

    def test_defaults(self):
        from src.agent.result import AgentResult
        r = AgentResult(context="", contexts_by_tool={}, sources=[], tool_trace=[])
        assert r.model_used == "local"
        assert r.partial is False
        assert r.warnings == []


# ===========================================================================
# AggregatorAgent._dedup_sources
# ===========================================================================

class TestDedupSources:
    def _dedup(self, sources):
        from src.agent.aggregator import AggregatorAgent
        return AggregatorAgent._dedup_sources(sources)

    def test_empty(self):
        assert self._dedup([]) == []

    def test_no_chunk_id_all_kept(self):
        sources = [{"filename": "a.pdf"}, {"filename": "b.pdf"}]
        result = self._dedup(sources)
        assert len(result) == 2

    def test_dedup_keeps_highest_similarity(self):
        sources = [
            {"chunk_id": 1, "similarity": 0.7, "filename": "a.pdf"},
            {"chunk_id": 1, "similarity": 0.9, "filename": "a.pdf"},  # higher — keep this
            {"chunk_id": 1, "similarity": 0.5, "filename": "a.pdf"},
        ]
        result = self._dedup(sources)
        assert len(result) == 1
        assert result[0]["similarity"] == 0.9

    def test_mixed_keyed_and_unkeyed(self):
        sources = [
            {"chunk_id": 10, "similarity": 0.8},
            {"chunk_id": 10, "similarity": 0.6},
            {"filename": "web"},  # no chunk_id
        ]
        result = self._dedup(sources)
        # 1 deduplicated chunk + 1 unkeyed = 2
        assert len(result) == 2
        assert result[0]["similarity"] == 0.8

    def test_different_chunk_ids_all_kept(self):
        sources = [
            {"chunk_id": 1, "similarity": 0.8},
            {"chunk_id": 2, "similarity": 0.7},
            {"chunk_id": 3, "similarity": 0.6},
        ]
        assert len(self._dedup(sources)) == 3


# ===========================================================================
# AggregatorAgent._resolve_tools / _resolve_queries
# ===========================================================================

class TestResolveHelpers:
    def test_explicit_tools_override_plan(self):
        from src.agent.aggregator import AggregatorAgent
        plan = _make_plan(tools=["web_search"])
        result = AggregatorAgent._resolve_tools(["local_docs"], plan)
        assert result == ["local_docs"]

    def test_plan_tools_used_when_no_explicit(self):
        from src.agent.aggregator import AggregatorAgent
        plan = _make_plan(tools=["web_search"])
        result = AggregatorAgent._resolve_tools(None, plan)
        assert result == ["web_search"]

    def test_default_tools_when_no_plan_no_explicit(self):
        from src.agent.aggregator import AggregatorAgent
        result = AggregatorAgent._resolve_tools(None, None)
        assert result == ["local_docs"]

    def test_empty_explicit_list_returns_empty(self):
        from src.agent.aggregator import AggregatorAgent
        result = AggregatorAgent._resolve_tools([], _make_plan())
        assert result == []

    def test_resolve_queries_single_hop_no_sub_questions(self):
        from src.agent.aggregator import AggregatorAgent
        # estimated_hops=1, no sub_questions → not multi-hop → uses original query
        plan = _make_plan(sub_questions=[], estimated_hops=1)
        result = AggregatorAgent._resolve_queries("original", plan)
        assert result == ["original"]

    def test_resolve_queries_single_sub_question_not_multi_hop(self):
        from src.agent.aggregator import AggregatorAgent
        # 1 sub-question and hops=1 → is_multi_hop=False → original query
        plan = _make_plan(sub_questions=["q1"], estimated_hops=1)
        result = AggregatorAgent._resolve_queries("original", plan)
        assert result == ["original"]

    def test_resolve_queries_multi_hop_uses_sub_questions(self):
        from src.agent.aggregator import AggregatorAgent
        plan = _make_plan(sub_questions=["q1", "q2"], estimated_hops=2)
        result = AggregatorAgent._resolve_queries("original", plan)
        assert result == ["q1", "q2"]

    def test_resolve_queries_no_plan(self):
        from src.agent.aggregator import AggregatorAgent
        result = AggregatorAgent._resolve_queries("my query", None)
        assert result == ["my query"]


# ===========================================================================
# AggregatorAgent.run() — integration-style with mocked ToolRouter
# ===========================================================================

class TestAggregatorAgentRun:
    def test_single_tool_happy_path(self):
        from src.agent.aggregator import AggregatorAgent
        router = _make_router({"local_docs": {"context": "ctx", "sources": [{"chunk_id": 1, "similarity": 0.9}]}})
        agent = AggregatorAgent(tool_router=router)
        result = agent.run("what is X?", tools=["local_docs"])

        assert result.context == "ctx"
        assert result.contexts_by_tool["local_docs"] == "ctx"
        assert len(result.sources) == 1
        assert len(result.tool_trace) == 1
        assert result.tool_trace[0].success is True
        assert result.partial is False
        assert result.warnings == []

    def test_multi_tool_both_succeed(self):
        from src.agent.aggregator import AggregatorAgent
        router = _make_router({
            "local_docs": {"context": "local ctx", "sources": [{"chunk_id": 1, "similarity": 0.8}]},
            "web_search": {"context": "web ctx", "sources": []},
        })
        agent = AggregatorAgent(tool_router=router)
        result = agent.run("q", tools=["local_docs", "web_search"])

        assert "local ctx" in result.context
        assert "web ctx" in result.context
        assert result.contexts_by_tool["local_docs"] == "local ctx"
        assert result.contexts_by_tool["web_search"] == "web ctx"
        assert result.partial is False
        assert len(result.tool_trace) == 2

    def test_partial_failure_one_tool_fails(self):
        from src.agent.aggregator import AggregatorAgent
        router = _make_router({
            "local_docs": {"context": "ok", "sources": []},
            "web_search": "FAIL",
        })
        agent = AggregatorAgent(tool_router=router)
        result = agent.run("q", tools=["local_docs", "web_search"], max_retries=0)

        assert result.partial is True
        assert len(result.warnings) == 1
        assert "web_search" in result.warnings[0]
        assert result.context == "ok"  # local succeeded

    def test_all_tools_fail_returns_empty_partial_false(self):
        from src.agent.aggregator import AggregatorAgent
        router = _make_router({"local_docs": "FAIL", "web_search": "FAIL"})
        agent = AggregatorAgent(tool_router=router)
        result = agent.run("q", tools=["local_docs", "web_search"], max_retries=0)

        assert result.context == ""
        assert result.sources == []
        # partial only when SOME succeed — if ALL fail, partial=False
        assert result.partial is False
        assert len(result.warnings) == 2

    def test_multi_hop_dispatches_sub_questions(self):
        from src.agent.aggregator import AggregatorAgent
        calls = []
        def dispatch(tool_name, query, filters, top_k):
            calls.append((tool_name, query))
            return {"context": f"ctx-{query}", "sources": []}

        router = MagicMock()
        router.dispatch.side_effect = dispatch
        agent = AggregatorAgent(tool_router=router)
        plan = _make_plan(sub_questions=["q1", "q2"], estimated_hops=2)
        result = agent.run("original", plan=plan, tools=["local_docs"])

        dispatched_queries = {q for _, q in calls}
        assert "q1" in dispatched_queries
        assert "q2" in dispatched_queries
        assert len(result.tool_trace) == 2  # one per sub-question

    def test_retry_succeeds_on_second_attempt(self):
        from src.agent.aggregator import AggregatorAgent

        attempt_counter = {"n": 0}
        def dispatch(tool_name, query, filters, top_k):
            attempt_counter["n"] += 1
            if attempt_counter["n"] < 2:
                raise RuntimeError("transient error")
            return {"context": "recovered", "sources": []}

        router = MagicMock()
        router.dispatch.side_effect = dispatch
        agent = AggregatorAgent(tool_router=router)
        result = agent.run("q", tools=["local_docs"], max_retries=1)

        assert result.context == "recovered"
        assert result.tool_trace[0].success is True
        assert attempt_counter["n"] == 2

    def test_dedup_across_sub_questions(self):
        """Same chunk returned by two sub-question queries must appear once."""
        from src.agent.aggregator import AggregatorAgent
        call_n = {"n": 0}
        def dispatch(tool_name, query, filters, top_k):
            call_n["n"] += 1
            # Both sub-questions return the same chunk_id=99
            return {
                "context": f"ctx-{call_n['n']}",
                "sources": [{"chunk_id": 99, "similarity": 0.7 + call_n["n"] * 0.1}],
            }

        router = MagicMock()
        router.dispatch.side_effect = dispatch
        agent = AggregatorAgent(tool_router=router)
        plan = _make_plan(sub_questions=["q1", "q2"], estimated_hops=2)
        result = agent.run("original", plan=plan, tools=["local_docs"])

        # Should keep the one with higher similarity
        assert len(result.sources) == 1
        assert result.sources[0]["similarity"] > 0.7

    def test_empty_tools_list_returns_empty_result(self):
        from src.agent.aggregator import AggregatorAgent
        router = MagicMock()
        agent = AggregatorAgent(tool_router=router)
        result = agent.run("q", tools=[])

        assert result.context == ""
        assert result.sources == []
        assert result.tool_trace == []
        router.dispatch.assert_not_called()

    def test_tool_trace_counts_results(self):
        from src.agent.aggregator import AggregatorAgent
        router = _make_router({
            "local_docs": {"context": "ctx", "sources": [{"chunk_id": 1}, {"chunk_id": 2}]},
        })
        agent = AggregatorAgent(tool_router=router)
        result = agent.run("q", tools=["local_docs"])
        assert result.tool_trace[0].result_count == 2

    def test_latency_recorded(self):
        from src.agent.aggregator import AggregatorAgent
        router = _make_router({"local_docs": {"context": "", "sources": []}})
        agent = AggregatorAgent(tool_router=router)
        result = agent.run("q", tools=["local_docs"])
        assert result.tool_trace[0].latency_ms >= 0


# ===========================================================================
# ToolRouter.dispatch()
# ===========================================================================

class TestToolRouterDispatch:
    def test_unknown_tool_raises_value_error(self):
        from src.agent.tool_router import ToolRouter
        with pytest.raises(ValueError, match="Unknown tool"):
            ToolRouter().dispatch("does_not_exist", "q")

    def test_cloud_connectors_returns_empty_when_mcp_disabled(self):
        from src.agent.tool_router import ToolRouter
        with patch("src.config.MCP_ENABLED", False):
            result = ToolRouter()._cloud_connectors("q", {}, 10)
        assert result == {"context": "", "sources": []}

    def test_dispatch_routes_to_local_docs_method(self):
        """dispatch("local_docs", ...) calls _local_docs with correct args."""
        from src.agent.tool_router import ToolRouter
        router = ToolRouter()
        with patch.object(router, "_local_docs", return_value={"context": "c", "sources": []}) as m:
            result = router.dispatch("local_docs", "q", {"filenames": ["a.pdf"]}, 5)
            m.assert_called_once_with("q", {"filenames": ["a.pdf"]}, 5)
        assert result["context"] == "c"

    def test_dispatch_routes_to_web_search_method(self):
        from src.agent.tool_router import ToolRouter
        router = ToolRouter()
        with patch.object(router, "_web_search", return_value={"context": "w", "sources": []}) as m:
            router.dispatch("web_search", "query")
            m.assert_called_once_with("query")

    def test_dispatch_routes_to_cloud_connectors_method(self):
        from src.agent.tool_router import ToolRouter
        router = ToolRouter()
        with patch.object(router, "_cloud_connectors", return_value={"context": "", "sources": []}) as m:
            router.dispatch("cloud_connectors", "q", {}, 3)
            m.assert_called_once_with("q", {}, 3)

    def test_web_search_direct_path_returns_context_string(self):
        from src.agent.tool_router import ToolRouter
        mock_provider = MagicMock()
        mock_provider.search.return_value = []
        mock_provider.format_web_context.return_value = "formatted web ctx"

        with patch("src.config.MCP_ENABLED", False), \
             patch("src.rag.web_search.WebSearchProvider", return_value=mock_provider):
            router = ToolRouter()
            result = router._web_search("who is X?")
        # The method imports WebSearchProvider locally; test that context is a string
        assert isinstance(result["context"], str)
        assert result["sources"] == []

    def test_all_tool_names_route_without_error(self):
        """Each canonical tool name should be dispatched without ValueError."""
        from src.agent.tool_router import ALL_TOOLS, ToolRouter
        router = ToolRouter()
        for tool in ALL_TOOLS:
            method_name = {
                "local_docs": "_local_docs",
                "web_search": "_web_search",
                "cloud_connectors": "_cloud_connectors",
            }[tool]
            with patch.object(router, method_name, return_value={"context": "", "sources": []}):
                result = router.dispatch(tool, "q")
                assert "context" in result
