"""
Aggregator Agent
================

Custom lightweight ReAct-style orchestrator that:

1. Parses a QueryPlan into a set of (tool, query) dispatch jobs.
2. Executes all jobs in parallel via ThreadPoolExecutor.
3. Retries transient tool failures (configurable).
4. Merges results across tools and sub-questions.
5. Deduplicates sources by chunk_id (highest similarity wins).
6. Returns a structured AgentResult with full observability.

This is intentionally thin (~200 lines, zero external deps beyond the
standard library).  The goal is a fully auditable dispatch loop.
Migrate to LangGraph if orchestration complexity grows beyond what this
loop handles cleanly.

Usage (when AGGREGATOR_AGENT_ENABLED=true in config):

    from src.agent import AggregatorAgent

    agent = AggregatorAgent()
    result = agent.run(
        query="What is the refund policy?",
        plan=query_plan,          # from QueryPlanner (optional)
        filename_filter=["tos.pdf"],
        tools=["local_docs"],
    )
    # result.context        → merged context block
    # result.contexts_by_tool → {"local_docs": "..."}
    # result.sources        → deduplicated list[dict]
    # result.tool_trace     → [{tool, query, success, latency_ms}, ...]
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from ..utils.logging_config import get_logger
from .result import AgentResult, ToolCall
from .tool_router import ToolRouter

if TYPE_CHECKING:
    from ..rag.planner import QueryPlan

logger = get_logger(__name__)

# Maximum parallel tool jobs — keeps resource use bounded even for large plans.
_MAX_PARALLEL = 4

# Default tool when no plan is available and no explicit list is given.
_DEFAULT_TOOLS = ["local_docs"]


class AggregatorAgent:
    """
    Parallel tool dispatcher and result synthesizer.

    Thread-safe: a single instance may be shared across requests.
    All state is local to each run() call.
    """

    def __init__(self, tool_router: ToolRouter | None = None) -> None:
        self._router = tool_router or ToolRouter()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        query: str,
        plan: QueryPlan | None = None,
        filename_filter: list[str] | None = None,
        tools: list[str] | None = None,
        top_k: int = 10,
        max_retries: int = 1,
    ) -> AgentResult:
        """
        Execute tool dispatch and return merged results.

        Args:
            query:           User's original (cleaned) query.
            plan:            QueryPlan from QueryPlanner (optional).
                             Provides sub_questions for multi-hop and a
                             default tools list.
            filename_filter: Restrict local_docs retrieval to these files.
            tools:           Explicit tool list — overrides plan.tools.
                             Pass an empty list to skip all retrieval.
            top_k:           Max chunks requested from local_docs.
            max_retries:     Extra attempts per job on failure (1 = 2 total).

        Returns:
            AgentResult — never raises; partial failures set partial=True.
        """
        effective_tools = self._resolve_tools(tools, plan)
        queries = self._resolve_queries(query, plan)
        filters = {"filenames": filename_filter or []}

        jobs = [(tool, q) for tool in effective_tools for q in queries]
        logger.info(
            f"[Agent] {len(jobs)} job(s) — "
            f"{len(effective_tools)} tool(s) × {len(queries)} query/queries"
        )

        tool_trace: list[ToolCall] = []
        contexts_by_tool: dict[str, list[str]] = {t: [] for t in effective_tools}
        all_sources: list[dict] = []
        warnings: list[str] = []

        if not jobs:
            return AgentResult(
                context="", contexts_by_tool={}, sources=[],
                tool_trace=[], partial=False, warnings=[],
            )

        with ThreadPoolExecutor(max_workers=min(len(jobs), _MAX_PARALLEL)) as pool:
            future_to_job = {
                pool.submit(
                    self._dispatch_with_retry, tool, q, filters, top_k, max_retries
                ): (tool, q)
                for tool, q in jobs
            }
            for future in as_completed(future_to_job):
                tool, q = future_to_job[future]
                try:
                    result, latency_ms = future.result()
                    ctx = result.get("context") or ""
                    srcs = result.get("sources") or []
                    if ctx:
                        contexts_by_tool[tool].append(ctx)
                    all_sources.extend(srcs)
                    tool_trace.append(ToolCall(
                        tool=tool, query=q, success=True,
                        result_count=len(srcs), latency_ms=latency_ms,
                    ))
                    logger.debug(
                        f"[Agent] OK  {tool!r} '{q[:40]}' "
                        f"→ {len(srcs)} src, {latency_ms:.0f}ms"
                    )
                except Exception as exc:
                    tool_trace.append(ToolCall(
                        tool=tool, query=q, success=False,
                        latency_ms=0.0, error=str(exc),
                    ))
                    msg = f"{tool}: {exc}"
                    warnings.append(msg)
                    logger.warning(f"[Agent] FAIL {tool!r} '{q[:40]}' — {exc}")

        merged_by_tool: dict[str, str] = {
            t: "\n\n".join(ctxs)
            for t, ctxs in contexts_by_tool.items()
            if ctxs
        }
        combined = "\n\n".join(c for c in merged_by_tool.values() if c)
        merged_sources = self._dedup_sources(all_sources)

        any_ok = any(tc.success for tc in tool_trace)
        any_fail = any(not tc.success for tc in tool_trace)

        result_obj = AgentResult(
            context=combined,
            contexts_by_tool=merged_by_tool,
            sources=merged_sources,
            tool_trace=tool_trace,
            partial=any_ok and any_fail,
            warnings=warnings,
        )
        logger.info(
            f"[Agent] Done — {len(merged_sources)} sources, "
            f"partial={result_obj.partial}, warnings={len(warnings)}"
        )
        return result_obj

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_tools(
        tools: list[str] | None,
        plan: QueryPlan | None,
    ) -> list[str]:
        """Determine the effective tool list from explicit arg or plan."""
        if tools is not None:
            return tools if tools else []
        if plan is not None and plan.tools:
            return plan.tools
        return _DEFAULT_TOOLS

    @staticmethod
    def _resolve_queries(
        query: str,
        plan: QueryPlan | None,
    ) -> list[str]:
        """Use sub-questions for multi-hop plans; otherwise the original query."""
        if plan is not None and plan.is_multi_hop and plan.sub_questions:
            return plan.sub_questions
        return [query]

    def _dispatch_with_retry(
        self,
        tool: str,
        query: str,
        filters: dict,
        top_k: int,
        max_retries: int,
    ) -> tuple[dict, float]:
        """
        Call ToolRouter.dispatch with retry on exception.

        Returns (result_dict, latency_ms).
        Raises the last exception once all attempts are exhausted.
        """
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            t0 = time.monotonic()
            try:
                result = self._router.dispatch(tool, query, filters, top_k)
                return result, (time.monotonic() - t0) * 1000
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    logger.warning(
                        f"[Agent] {tool!r} attempt {attempt + 1}/{max_retries + 1} failed: {exc}"
                    )
        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _dedup_sources(sources: list[dict]) -> list[dict]:
        """
        Deduplicate by chunk_id, keeping the entry with the highest
        similarity score.  Sources without a chunk_id (e.g. web results)
        are always preserved as-is.
        """
        keyed: dict[int, dict] = {}
        unkeyed: list[dict] = []
        for s in sources:
            cid = s.get("chunk_id")
            if cid is None:
                unkeyed.append(s)
            elif cid not in keyed or s.get("similarity", 0) > keyed[cid].get("similarity", 0):
                keyed[cid] = s
        return list(keyed.values()) + unkeyed
