"""
Tests for src/rag/planner.py

Covers:
  - QueryPlan dataclass: defaults, to_dict, is_multi_hop property
  - QueryPlanner.plan: success path, LLM exception → None, empty response → None,
    correct args forwarded to ollama_client
  - QueryPlanner._parse: valid JSON, JSON embedded in prose, no JSON → ValueError,
    missing fields fall back to defaults, empty/blank sub_questions fall back,
    sub_questions capped at 3, estimated_hops clamped to [1,3],
    synthesis_required coercion, invalid JSON body → propagates
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.rag.planner import _JSON_RE, QueryPlan, QueryPlanner

# ===========================================================================
# QueryPlan dataclass
# ===========================================================================

class TestQueryPlan:
    def test_defaults(self):
        plan = QueryPlan()
        assert plan.intent == "factual_lookup"
        assert plan.sub_questions == []
        assert plan.tools == ["local_docs"]
        assert plan.synthesis_required is False
        assert plan.estimated_hops == 1

    def test_to_dict_roundtrip(self):
        plan = QueryPlan(
            intent="comparison",
            sub_questions=["What is A?", "What is B?"],
            tools=["local_docs", "web_search"],
            synthesis_required=True,
            estimated_hops=2,
        )
        d = plan.to_dict()
        assert d == {
            "intent": "comparison",
            "sub_questions": ["What is A?", "What is B?"],
            "tools": ["local_docs", "web_search"],
            "synthesis_required": True,
            "estimated_hops": 2,
        }

    def test_to_dict_keys_present(self):
        d = QueryPlan().to_dict()
        assert set(d) == {"intent", "sub_questions", "tools", "synthesis_required", "estimated_hops"}

    def test_is_multi_hop_false_by_default(self):
        plan = QueryPlan(estimated_hops=1, sub_questions=["single question"])
        assert plan.is_multi_hop is False

    def test_is_multi_hop_true_when_hops_gt_1(self):
        plan = QueryPlan(estimated_hops=2, sub_questions=["q"])
        assert plan.is_multi_hop is True

    def test_is_multi_hop_true_when_multiple_sub_questions(self):
        plan = QueryPlan(estimated_hops=1, sub_questions=["q1", "q2"])
        assert plan.is_multi_hop is True

    def test_is_multi_hop_true_when_both(self):
        plan = QueryPlan(estimated_hops=3, sub_questions=["q1", "q2", "q3"])
        assert plan.is_multi_hop is True


# ===========================================================================
# QueryPlanner._parse (static method — tested directly)
# ===========================================================================

class TestQueryPlannerParse:
    def _parse(self, raw, fallback="fallback query"):
        return QueryPlanner._parse(raw, fallback)

    # ── Happy path ────────────────────────────────────────────────────────────

    def test_parses_full_valid_json(self):
        raw = json.dumps({
            "intent": "comparison",
            "sub_questions": ["What is A?", "What is B?"],
            "tools": ["local_docs"],
            "synthesis_required": True,
            "estimated_hops": 2,
        })
        plan = self._parse(raw)
        assert plan.intent == "comparison"
        assert plan.sub_questions == ["What is A?", "What is B?"]
        assert plan.tools == ["local_docs"]
        assert plan.synthesis_required is True
        assert plan.estimated_hops == 2

    def test_parses_json_embedded_in_prose(self):
        payload = json.dumps({"intent": "synthesis", "sub_questions": ["Summarise docs"], "tools": ["local_docs"], "synthesis_required": False, "estimated_hops": 1})
        raw = f"Sure, here is the plan:\n{payload}\nDone."
        plan = self._parse(raw)
        assert plan.intent == "synthesis"

    def test_simple_factual_lookup(self):
        raw = json.dumps({
            "intent": "factual_lookup",
            "sub_questions": ["What is the retention policy?"],
            "tools": ["local_docs"],
            "synthesis_required": False,
            "estimated_hops": 1,
        })
        plan = self._parse(raw)
        assert plan.is_multi_hop is False

    # ── No JSON found ─────────────────────────────────────────────────────────

    def test_raises_value_error_when_no_json(self):
        with pytest.raises(ValueError, match="No JSON object found"):
            self._parse("I cannot produce a plan right now.")

    def test_raises_on_empty_string(self):
        with pytest.raises(ValueError):
            self._parse("")

    # ── Missing fields fall back to defaults ──────────────────────────────────

    def test_missing_intent_defaults_to_factual_lookup(self):
        raw = json.dumps({"sub_questions": ["q"], "tools": ["local_docs"], "synthesis_required": False, "estimated_hops": 1})
        plan = self._parse(raw)
        assert plan.intent == "factual_lookup"

    def test_missing_sub_questions_falls_back_to_query(self):
        raw = json.dumps({"intent": "general", "tools": ["local_docs"], "synthesis_required": False, "estimated_hops": 1})
        plan = self._parse(raw, fallback="what is X?")
        assert plan.sub_questions == ["what is X?"]

    def test_null_sub_questions_falls_back_to_query(self):
        raw = json.dumps({"intent": "general", "sub_questions": None, "tools": [], "synthesis_required": False, "estimated_hops": 1})
        plan = self._parse(raw, fallback="backup")
        assert plan.sub_questions == ["backup"]

    def test_empty_list_sub_questions_falls_back_to_query(self):
        raw = json.dumps({"intent": "general", "sub_questions": [], "tools": [], "synthesis_required": False, "estimated_hops": 1})
        plan = self._parse(raw, fallback="my question")
        assert plan.sub_questions == ["my question"]

    def test_blank_string_sub_questions_filtered_and_falls_back(self):
        raw = json.dumps({"intent": "general", "sub_questions": ["   ", ""], "tools": [], "synthesis_required": False, "estimated_hops": 1})
        plan = self._parse(raw, fallback="fallback q")
        assert plan.sub_questions == ["fallback q"]

    def test_missing_tools_defaults_to_local_docs(self):
        raw = json.dumps({"intent": "factual_lookup", "sub_questions": ["q"], "synthesis_required": False, "estimated_hops": 1})
        plan = self._parse(raw)
        assert plan.tools == ["local_docs"]

    def test_null_tools_defaults_to_local_docs(self):
        raw = json.dumps({"intent": "factual_lookup", "sub_questions": ["q"], "tools": None, "synthesis_required": False, "estimated_hops": 1})
        plan = self._parse(raw)
        assert plan.tools == ["local_docs"]

    # ── sub_questions capped at 3 ─────────────────────────────────────────────

    def test_sub_questions_capped_at_three(self):
        raw = json.dumps({
            "intent": "synthesis",
            "sub_questions": ["q1", "q2", "q3", "q4", "q5"],
            "tools": ["local_docs"],
            "synthesis_required": True,
            "estimated_hops": 3,
        })
        plan = self._parse(raw)
        assert len(plan.sub_questions) == 3
        assert plan.sub_questions == ["q1", "q2", "q3"]

    # ── estimated_hops clamped to [1, 3] ──────────────────────────────────────

    def test_hops_zero_clamped_to_one(self):
        raw = json.dumps({"intent": "factual_lookup", "sub_questions": ["q"], "tools": [], "synthesis_required": False, "estimated_hops": 0})
        plan = self._parse(raw)
        assert plan.estimated_hops == 1

    def test_hops_negative_clamped_to_one(self):
        raw = json.dumps({"intent": "factual_lookup", "sub_questions": ["q"], "tools": [], "synthesis_required": False, "estimated_hops": -5})
        plan = self._parse(raw)
        assert plan.estimated_hops == 1

    def test_hops_above_three_clamped_to_three(self):
        raw = json.dumps({"intent": "synthesis", "sub_questions": ["q"], "tools": [], "synthesis_required": True, "estimated_hops": 10})
        plan = self._parse(raw)
        assert plan.estimated_hops == 3

    def test_hops_two_preserved(self):
        raw = json.dumps({"intent": "comparison", "sub_questions": ["q"], "tools": [], "synthesis_required": False, "estimated_hops": 2})
        plan = self._parse(raw)
        assert plan.estimated_hops == 2

    def test_missing_hops_defaults_to_one(self):
        raw = json.dumps({"intent": "factual_lookup", "sub_questions": ["q"], "tools": []})
        plan = self._parse(raw)
        assert plan.estimated_hops == 1

    # ── synthesis_required coercion ───────────────────────────────────────────

    def test_synthesis_required_truthy_string(self):
        raw = json.dumps({"intent": "synthesis", "sub_questions": ["q"], "tools": [], "synthesis_required": "yes", "estimated_hops": 1})
        plan = self._parse(raw)
        assert plan.synthesis_required is True

    def test_synthesis_required_false(self):
        raw = json.dumps({"intent": "factual_lookup", "sub_questions": ["q"], "tools": [], "synthesis_required": False, "estimated_hops": 1})
        plan = self._parse(raw)
        assert plan.synthesis_required is False

    # ── Invalid JSON body (valid regex match but unparseable) ─────────────────

    def test_invalid_json_body_raises(self):
        # Regex will match `{broken` up to the last `}` if one exists; craft a
        # string where the regex matches but json.loads fails.
        raw = "{not: valid json}"
        with pytest.raises(Exception):  # json.JSONDecodeError
            self._parse(raw)


# ===========================================================================
# QueryPlanner.plan (integration with mocked ollama_client)
# ===========================================================================

class TestQueryPlannerPlan:
    def _planner(self):
        return QueryPlanner()

    def _make_client(self, response: str):
        """Return a mock ollama_client whose generate_chat_response yields response."""
        client = MagicMock()
        client.generate_chat_response.return_value = iter([response])
        return client

    def _valid_json_response(self, **overrides):
        base = {
            "intent": "factual_lookup",
            "sub_questions": ["What is the policy?"],
            "tools": ["local_docs"],
            "synthesis_required": False,
            "estimated_hops": 1,
        }
        base.update(overrides)
        return json.dumps(base)

    # ── Success paths ─────────────────────────────────────────────────────────

    def test_returns_query_plan_on_success(self):
        planner = self._planner()
        client = self._make_client(self._valid_json_response())
        result = planner.plan("What is the policy?", "llama3", client)
        assert isinstance(result, QueryPlan)
        assert result.intent == "factual_lookup"

    def test_calls_ollama_with_correct_args(self):
        planner = self._planner()
        client = self._make_client(self._valid_json_response())
        planner.plan("test query", "my-model", client)
        client.generate_chat_response.assert_called_once()
        call_args = client.generate_chat_response.call_args
        # positional: model, messages
        assert call_args.args[0] == "my-model"
        messages = call_args.args[1]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "test query" in messages[1]["content"]
        # keyword: stream=False, temperature=0.0
        assert call_args.kwargs.get("stream") is False
        assert call_args.kwargs.get("temperature") == 0.0

    def test_returns_plan_with_correct_sub_questions(self):
        planner = self._planner()
        client = self._make_client(self._valid_json_response(
            intent="comparison",
            sub_questions=["What is A?", "What is B?"],
            estimated_hops=2,
        ))
        result = planner.plan("Compare A and B", "llama3", client)
        assert result.sub_questions == ["What is A?", "What is B?"]
        assert result.is_multi_hop is True

    # ── Failure paths return None (non-blocking) ──────────────────────────────

    def test_returns_none_when_llm_raises(self):
        planner = self._planner()
        client = MagicMock()
        client.generate_chat_response.side_effect = RuntimeError("Ollama down")
        result = planner.plan("query", "llama3", client)
        assert result is None

    def test_returns_none_when_response_is_empty(self):
        planner = self._planner()
        client = MagicMock()
        # Empty iterator → next(iter(...), "") gives "" → _parse raises → caught
        client.generate_chat_response.return_value = iter([])
        result = planner.plan("query", "llama3", client)
        assert result is None

    def test_returns_none_when_response_has_no_json(self):
        planner = self._planner()
        client = self._make_client("I cannot help with that.")
        result = planner.plan("query", "llama3", client)
        assert result is None

    def test_returns_none_when_json_is_invalid(self):
        planner = self._planner()
        client = self._make_client("{broken json}")
        result = planner.plan("query", "llama3", client)
        assert result is None

    def test_returns_none_when_iterator_raises_mid_stream(self):
        planner = self._planner()
        client = MagicMock()
        def bad_gen():
            raise ConnectionError("stream interrupted")
            yield  # make it a generator
        client.generate_chat_response.return_value = bad_gen()
        result = planner.plan("query", "llama3", client)
        assert result is None

    # ── Logging smoke-test ────────────────────────────────────────────────────

    def test_logs_intent_on_success(self):
        planner = self._planner()
        client = self._make_client(self._valid_json_response(intent="synthesis", estimated_hops=2))
        with patch("src.rag.planner.logger") as mock_logger:
            planner.plan("summarise everything", "llama3", client)
        mock_logger.info.assert_called_once()
        log_msg = mock_logger.info.call_args.args[0]
        assert "synthesis" in log_msg
        assert "2" in log_msg

    def test_logs_debug_on_failure(self):
        planner = self._planner()
        client = MagicMock()
        client.generate_chat_response.side_effect = Exception("boom")
        with patch("src.rag.planner.logger") as mock_logger:
            planner.plan("query", "llama3", client)
        mock_logger.debug.assert_called_once()
