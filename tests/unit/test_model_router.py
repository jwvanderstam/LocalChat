"""
Tests for src/agent/models.py (ModelRegistry) and src/agent/router.py (ModelRouter).

Covers:
  - ModelRegistry: default config, env-var override, resolve fallback
  - ModelRegistry.summary() serialisation
  - ModelRouter._is_fast: boundary conditions
  - ModelRouter._classify: VISION, CODE, LARGE, FAST, BASE routes
  - ModelRouter.select: returns (model_id, rationale), falls back to active model
  - Edge cases: empty query, no plan, plan with synthesis_required=False
"""

import os
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(hops=1, synthesis=False, sub_questions=None, tools=None):
    from src.rag.planner import QueryPlan
    return QueryPlan(
        intent="factual_lookup",
        sub_questions=sub_questions or [],
        tools=tools or ["local_docs"],
        synthesis_required=synthesis,
        estimated_hops=hops,
    )


# ===========================================================================
# ModelClass
# ===========================================================================

class TestModelClass:
    def test_all_values_are_strings(self):
        from src.agent.models import ModelClass
        for cls in ModelClass:
            assert isinstance(cls.value, str)

    def test_expected_classes_exist(self):
        from src.agent.models import ModelClass
        assert {c.value for c in ModelClass} == {"fast", "base", "large", "code", "vision"}


# ===========================================================================
# ModelRegistry
# ===========================================================================

class TestModelRegistry:
    def test_default_model_ids_are_empty(self):
        """Without env vars, all model_ids should be empty strings."""
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("MODEL_FAST", "MODEL_BASE", "MODEL_LARGE",
                                  "MODEL_CODE", "MODEL_VISION")}
        with patch.dict(os.environ, clean_env, clear=True):
            from src.agent.models import ModelClass, ModelRegistry
            reg = ModelRegistry()
            for cls in ModelClass:
                assert reg._registry[cls].model_id == ""

    def test_env_var_sets_model_id(self):
        from src.agent.models import ModelClass, ModelRegistry
        with patch("src.config.MODEL_FAST", "llama3.2:3b"):
            reg = ModelRegistry()
            assert reg._registry[ModelClass.FAST].model_id == "llama3.2:3b"

    def test_resolve_returns_configured_id(self):
        from src.agent.models import ModelClass, ModelRegistry
        with patch("src.config.MODEL_CODE", "qwen2.5-coder:7b"):
            reg = ModelRegistry()
            assert reg.resolve(ModelClass.CODE, fallback="active") == "qwen2.5-coder:7b"

    def test_resolve_falls_back_when_not_configured(self):
        clean_env = {k: v for k, v in os.environ.items() if k != "MODEL_LARGE"}
        with patch.dict(os.environ, clean_env, clear=True):
            from src.agent.models import ModelClass, ModelRegistry
            reg = ModelRegistry()
            assert reg.resolve(ModelClass.LARGE, fallback="llama3.1:8b") == "llama3.1:8b"

    def test_summary_contains_all_classes(self):
        from src.agent.models import ModelClass, ModelRegistry
        reg = ModelRegistry()
        summary = reg.summary()
        assert set(summary.keys()) == {cls.value for cls in ModelClass}

    def test_summary_shows_configured_true(self):
        from src.agent.models import ModelClass, ModelRegistry
        with patch("src.config.MODEL_VISION", "llava:13b"):
            reg = ModelRegistry()
            assert reg.summary()[ModelClass.VISION.value]["configured"] is True

    def test_summary_shows_configured_false_for_empty(self):
        clean_env = {k: v for k, v in os.environ.items() if k != "MODEL_BASE"}
        with patch.dict(os.environ, clean_env, clear=True):
            from src.agent.models import ModelClass, ModelRegistry
            reg = ModelRegistry()
            assert reg.summary()[ModelClass.BASE.value]["configured"] is False


# ===========================================================================
# ModelRouter._is_fast
# ===========================================================================

class TestIsFast:
    def _is_fast(self, query, plan=None):
        from src.agent.router import ModelRouter
        return ModelRouter._is_fast(query, plan)

    def test_short_query_no_plan_is_fast(self):
        assert self._is_fast("What is X?") is True

    def test_query_at_boundary_is_fast(self):
        # Exactly 80 chars → still fast
        assert self._is_fast("a" * 80) is True

    def test_query_one_over_boundary_is_not_fast(self):
        assert self._is_fast("a" * 81) is False

    def test_multi_hop_plan_not_fast(self):
        assert self._is_fast("short", _make_plan(hops=2)) is False

    def test_synthesis_plan_not_fast(self):
        assert self._is_fast("short", _make_plan(synthesis=True)) is False

    def test_single_hop_no_synthesis_is_fast(self):
        assert self._is_fast("short", _make_plan(hops=1, synthesis=False)) is True


# ===========================================================================
# ModelRouter._classify
# ===========================================================================

class TestClassify:
    def _classify(self, query, plan=None, doc_types=None):
        from src.agent.models import ModelRegistry
        from src.agent.router import ModelRouter
        router = ModelRouter(registry=ModelRegistry())
        return router._classify(query, plan, doc_types or [])

    def test_vision_from_doc_type(self):
        from src.agent.models import ModelClass
        cls, reason = self._classify("what is shown?", doc_types=["IMAGE"])
        assert cls == ModelClass.VISION
        assert "image" in reason.lower()

    def test_vision_from_query_keyword(self):
        from src.agent.models import ModelClass
        cls, _ = self._classify("describe the diagram in the document")
        assert cls == ModelClass.VISION

    def test_code_from_doc_type(self):
        from src.agent.models import ModelClass
        cls, reason = self._classify("explain this", doc_types=["CODE_PYTHON"])
        assert cls == ModelClass.CODE
        assert "code" in reason.lower()

    def test_code_from_query_python_def(self):
        from src.agent.models import ModelClass
        cls, _ = self._classify("def calculate(x): return x * 2")
        assert cls == ModelClass.CODE

    def test_code_from_query_review_keyword(self):
        from src.agent.models import ModelClass
        cls, _ = self._classify("review my function for bugs")
        assert cls == ModelClass.CODE

    def test_large_for_multi_hop_synthesis(self):
        from src.agent.models import ModelClass
        plan = _make_plan(hops=2, synthesis=True)
        cls, reason = self._classify("compare all vendor proposals", plan=plan)
        assert cls == ModelClass.LARGE
        assert "2" in reason  # mentions hop count

    def test_large_requires_both_hops_and_synthesis(self):
        """hops >= 2 but synthesis_required=False should NOT route to LARGE."""
        from src.agent.models import ModelClass
        plan = _make_plan(hops=2, synthesis=False)
        cls, _ = self._classify("short", plan=plan)
        assert cls != ModelClass.LARGE

    def test_fast_for_short_simple_query(self):
        from src.agent.models import ModelClass
        cls, _ = self._classify("What is X?")
        assert cls == ModelClass.FAST

    def test_base_for_medium_query_no_signals(self):
        from src.agent.models import ModelClass
        # > 80 chars, no code/image/synthesis signals → BASE
        query = "What were the main conclusions from the quarterly financial report for fiscal year 2025?"
        assert len(query) > 80
        cls, _ = self._classify(query)
        assert cls == ModelClass.BASE

    def test_vision_priority_over_code(self):
        """Image doc_type should win over code markers in query."""
        from src.agent.models import ModelClass
        cls, _ = self._classify("def foo(): pass", doc_types=["IMAGE"])
        assert cls == ModelClass.VISION

    def test_code_priority_over_large(self):
        """Code doc_type should win over multi-hop synthesis plan."""
        from src.agent.models import ModelClass
        plan = _make_plan(hops=2, synthesis=True)
        cls, _ = self._classify("explain this", plan=plan, doc_types=["CODE_JS"])
        assert cls == ModelClass.CODE

    def test_empty_query_returns_valid_class(self):
        from src.agent.models import ModelClass
        cls, _ = self._classify("")
        assert cls in list(ModelClass)


# ===========================================================================
# ModelRouter.select (end-to-end)
# ===========================================================================

class TestModelRouterSelect:
    def test_returns_active_model_when_class_not_configured(self):
        """When MODEL_FAST is not set, FAST class should fall back to active model."""
        clean_env = {k: v for k, v in os.environ.items() if k != "MODEL_FAST"}
        with patch.dict(os.environ, clean_env, clear=True):
            from src.agent.models import ModelRegistry
            from src.agent.router import ModelRouter
            router = ModelRouter(registry=ModelRegistry())
            model_id, rationale = router.select("short", active_model="llama3.2:latest")
            assert model_id == "llama3.2:latest"
            assert "fast" in rationale.lower()

    def test_returns_configured_model_when_set(self):
        from src.agent.models import ModelRegistry
        from src.agent.router import ModelRouter
        with patch("src.config.MODEL_FAST", "llama3.2:3b"):
            router = ModelRouter(registry=ModelRegistry())
            model_id, rationale = router.select("short query")
            assert model_id == "llama3.2:3b"

    def test_rationale_includes_class_name(self):
        from src.agent.models import ModelRegistry
        from src.agent.router import ModelRouter
        router = ModelRouter(registry=ModelRegistry())
        _, rationale = router.select("What is X?", active_model="m")
        assert any(cls in rationale for cls in ["fast", "base", "large", "code", "vision"])

    def test_fallback_to_active_when_no_model_configured(self):
        """All classes unconfigured → every query uses active model."""
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("MODEL_FAST", "MODEL_BASE", "MODEL_LARGE",
                                  "MODEL_CODE", "MODEL_VISION")}
        with patch.dict(os.environ, clean_env, clear=True):
            from src.agent.models import ModelRegistry
            from src.agent.router import ModelRouter
            router = ModelRouter(registry=ModelRegistry())
            active = "my-active-model:latest"
            for query in ["short", "def foo(): pass", "a" * 200]:
                model_id, _ = router.select(query, active_model=active)
                assert model_id == active

    def test_vision_query_routes_to_vision_model(self):
        from src.agent.models import ModelRegistry
        from src.agent.router import ModelRouter
        with patch("src.config.MODEL_VISION", "llava:13b"):
            router = ModelRouter(registry=ModelRegistry())
            model_id, rationale = router.select(
                "describe the chart", doc_types=["IMAGE"], active_model="base"
            )
            assert model_id == "llava:13b"
            assert "vision" in rationale.lower()

    def test_code_query_routes_to_code_model(self):
        from src.agent.models import ModelRegistry
        from src.agent.router import ModelRouter
        with patch("src.config.MODEL_CODE", "qwen2.5-coder:7b"):
            router = ModelRouter(registry=ModelRegistry())
            model_id, _ = router.select("import numpy as np; print(x)", active_model="base")
            assert model_id == "qwen2.5-coder:7b"

    def test_large_synthesis_routes_to_large_model(self):
        from src.agent.models import ModelRegistry
        from src.agent.router import ModelRouter
        with patch("src.config.MODEL_LARGE", "llama3.1:70b"):
            router = ModelRouter(registry=ModelRegistry())
            plan = _make_plan(hops=3, synthesis=True)
            model_id, _ = router.select(
                "compare all vendor proposals in detail",
                plan=plan, active_model="base"
            )
            assert model_id == "llama3.1:70b"

    def test_never_raises(self):
        """Router must never raise regardless of input."""
        from src.agent.models import ModelRegistry
        from src.agent.router import ModelRouter
        router = ModelRouter(registry=ModelRegistry())
        inputs = [
            ("", None, None),
            ("x" * 10000, None, None),
            ("test", _make_plan(hops=99, synthesis=True), ["UNKNOWN_TYPE"]),
        ]
        for query, plan, doc_types in inputs:
            model_id, rationale = router.select(
                query, plan=plan, doc_types=doc_types, active_model="fallback"
            )
            assert isinstance(model_id, str)
            assert isinstance(rationale, str)
