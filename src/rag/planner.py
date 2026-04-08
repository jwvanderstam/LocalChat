"""
Query Planner
=============

Decomposes a user query into a structured plan before retrieval.

The planner makes one lightweight non-streaming LLM call, extracts JSON
from the response, and returns a ``QueryPlan`` dataclass.  All failures are
caught and return ``None`` so the rest of the chat pipeline is never blocked.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..utils.logging_config import get_logger

logger = get_logger(__name__)

_PLAN_SYSTEM_PROMPT = """\
You are a query planner.  Analyse the user query and output ONLY valid JSON
— no prose before or after the JSON.

Output schema:
{
  "intent": "<factual_lookup|comparison|synthesis|general>",
  "sub_questions": ["<question 1>", ...],
  "tools": ["local_docs"|"web_search"|"calculator"],
  "synthesis_required": <true|false>,
  "estimated_hops": <1|2|3>
}

Rules:
- intent: "factual_lookup" for direct single-fact questions; "comparison" for
  A-vs-B questions; "synthesis" for multi-document summarisation; "general"
  for chit-chat or questions that need no document retrieval.
- sub_questions: a list of the minimal set of questions that together answer
  the original query.  Usually 1; max 3.  Always include at least one entry.
- tools: list only the tools actually needed.
- synthesis_required: true only when two or more sub_questions must be combined.
- estimated_hops: 1 for simple, 2–3 for multi-hop.

Example (comparison):
{"intent":"comparison","sub_questions":["What is A's approach?","What is B's approach?"],"tools":["local_docs"],"synthesis_required":true,"estimated_hops":2}

Example (simple):
{"intent":"factual_lookup","sub_questions":["What is the retention policy?"],"tools":["local_docs"],"synthesis_required":false,"estimated_hops":1}
"""

_JSON_RE = re.compile(r'\{.*\}', re.DOTALL)


@dataclass
class QueryPlan:
    intent: str = "factual_lookup"
    sub_questions: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=lambda: ["local_docs"])
    synthesis_required: bool = False
    estimated_hops: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "sub_questions": self.sub_questions,
            "tools": self.tools,
            "synthesis_required": self.synthesis_required,
            "estimated_hops": self.estimated_hops,
        }

    @property
    def is_multi_hop(self) -> bool:
        return self.estimated_hops > 1 or len(self.sub_questions) > 1


class QueryPlanner:
    """Calls the active model to produce a structured QueryPlan for a query."""

    def plan(
        self,
        query: str,
        model: str,
        ollama_client: Any,
    ) -> QueryPlan | None:
        """
        Return a QueryPlan or None if planning fails.

        Args:
            query: Raw user query string.
            model: Active Ollama model name.
            ollama_client: OllamaClient instance.

        Returns:
            QueryPlan on success, None on any failure (non-blocking).
        """
        try:
            messages = [
                {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
                {"role": "user",   "content": f"Query: {query}"},
            ]
            # Non-streaming single-shot call; temperature=0 for determinism.
            raw = next(iter(
                ollama_client.generate_chat_response(
                    model, messages, stream=False, temperature=0.0
                )
            ), "")
            plan = self._parse(raw.strip(), query)
            logger.info(
                f"[Planner] intent={plan.intent} hops={plan.estimated_hops}"
                f" sub_questions={len(plan.sub_questions)}"
            )
            return plan
        except Exception as exc:
            logger.debug(f"[Planner] Planning failed (non-fatal): {exc}")
            return None

    @staticmethod
    def _parse(raw: str, fallback_query: str) -> QueryPlan:
        """Extract JSON from raw LLM output and coerce into a QueryPlan."""
        match = _JSON_RE.search(raw)
        if not match:
            raise ValueError(f"No JSON object found in planner output: {raw[:120]!r}")

        data = json.loads(match.group(0))

        intent = str(data.get("intent") or "factual_lookup")
        sub_questions: list[str] = data.get("sub_questions") or [fallback_query]
        # Guard: ensure at least one, all strings, max 3
        sub_questions = [str(q) for q in sub_questions if str(q).strip()][:3]
        if not sub_questions:
            sub_questions = [fallback_query]

        tools = [str(t) for t in (data.get("tools") or ["local_docs"])]
        synthesis_required = bool(data.get("synthesis_required", False))
        estimated_hops = max(1, min(int(data.get("estimated_hops") or 1), 3))

        return QueryPlan(
            intent=intent,
            sub_questions=sub_questions,
            tools=tools,
            synthesis_required=synthesis_required,
            estimated_hops=estimated_hops,
        )
