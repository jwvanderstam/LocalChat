"""
Agent Result Types
==================

Data classes for the output of AggregatorAgent.run().  Kept in a
separate module so they can be imported without pulling in the full
agent machinery (useful in tests and type annotations).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolCall:
    """Record of a single tool invocation during agent execution."""

    tool: str
    query: str
    success: bool
    result_count: int = 0
    latency_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "tool": self.tool,
            "query": self.query[:100],
            "success": self.success,
            "result_count": self.result_count,
            "latency_ms": round(self.latency_ms, 1),
            "error": self.error,
        }


@dataclass
class AgentResult:
    """
    Structured result returned by AggregatorAgent.run().

    Attributes:
        context:          Combined context string (all tools merged).
        contexts_by_tool: Per-tool context strings, keyed by tool name.
                          Use these when rendering tools differently
                          (e.g. "=== Local Docs ===" vs "=== Web ===").
        sources:          Deduplicated source list (chunk-level metadata).
        tool_trace:       Ordered log of every tool invocation.
        model_used:       Which model generated the final answer
                          (populated by the caller after synthesis).
        partial:          True when ≥1 tool succeeded and ≥1 tool failed.
        warnings:         Human-readable failure descriptions for each
                          failed tool call.
    """

    context: str
    contexts_by_tool: dict[str, str]
    sources: list[dict]
    tool_trace: list[ToolCall]
    model_used: str = "local"
    partial: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_trace_dict(self) -> list[dict]:
        """Serialisable tool trace — suitable for SSE payload and DB storage."""
        return [tc.to_dict() for tc in self.tool_trace]
