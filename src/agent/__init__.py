"""Aggregator Agent — parallel tool dispatch and result synthesis."""

from .aggregator import AggregatorAgent
from .result import AgentResult, ToolCall
from .tool_router import ToolRouter

__all__ = ["AggregatorAgent", "AgentResult", "ToolCall", "ToolRouter"]
