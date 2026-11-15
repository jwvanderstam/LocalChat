"""PC-3 — the reference plugin, end to end, through the real loader and the real tool loop.

The handles and the bus have their own unit tests (``test_plugin_contract.py``,
``test_hook_bus.py``). This proves they hold together: a plugin file loaded by
``PluginLoader`` gets every service, is subscribed to every hook, and its tool, called by
a model inside a request, sees that request's workspace, caller and settings.

The fixture lives in ``tests/fixtures/plugins/``, not ``plugins/``, so it survives the
``core-without-plugins`` job.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.plugins.hooks import HOOKS, HookBus
from src.tools.executor import ToolExecutor
from src.tools.plugin_loader import PluginLoader
from src.tools.registry import ToolRegistry
from src.utils.caller import RequestCaller, request_caller
from src.utils.scope import request_scope

pytestmark = pytest.mark.unit

_ECHO = Path(__file__).resolve().parents[1] / "fixtures" / "plugins" / "_echo.py"


class _Processor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def retrieve_context(self, query: str, **kwargs: Any) -> list[Any]:
        self.calls.append({"query": query, **kwargs})
        return [SimpleNamespace(chunk_text="body", filename="a.md", chunk_index=0,
                                similarity=0.9, metadata={})]


class _Echo:
    """The loaded fixture and what it was wired to."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.processor = _Processor()
        client = MagicMock()
        client.get_embedding_model.return_value = "nomic"
        client.generate_embedding.return_value = (True, [0.0] * 4)
        monkeypatch.setattr("src.rag.doc_processor", self.processor)
        monkeypatch.setattr("src.ollama_client.ollama_client", client)
        self.registry, self.bus = ToolRegistry(), HookBus()
        self.loader = PluginLoader(registry=self.registry, bus=self.bus)
        self.tools = self.loader.load_file(_ECHO)

    @property
    def module(self) -> ModuleType:
        return sys.modules["localchat_plugin__echo"]

    async def chat(self, arguments: dict[str, Any], caller: RequestCaller) -> dict[str, Any] | str:
        """A model calls ``echo`` once inside a request for workspace ``ws-a``; its reply."""
        seen: list[list[dict[str, Any]]] = []
        replies = iter([
            {"message": {"content": "", "tool_calls": [
                {"function": {"name": "echo", "arguments": arguments}}]}},
            {"message": {"content": "done"}},
        ])

        async def completion(model, messages, tools=None):
            seen.append(list(messages))
            return next(replies)

        client = MagicMock()
        client.generate_chat_completion = completion
        with patch("src.tools.executor.hook_bus", self.bus), request_scope("ws-a"), \
                request_caller(caller):
            out = [c async for c in ToolExecutor(client, self.registry).execute(
                "m", [{"role": "user", "content": "hi"}])]
        if "".join(out) != "done":
            raise AssertionError(f"the tool loop did not finish: {out!r}")
        reply = seen[-1][-1]["content"]
        try:
            return json.loads(reply)
        except ValueError:
            return reply


@pytest.fixture
def echo(monkeypatch: pytest.MonkeyPatch):
    loaded = _Echo(monkeypatch)
    yield loaded
    loaded.loader.unload("_echo")


class TestItLoadsOnTheContract:
    def test_it_loads_through_setup_not_as_a_legacy_plugin(self, echo):
        [info] = echo.loader.list_plugins()
        assert (info["legacy"], info["error"], echo.tools) == (False, None, ["echo"])

    def test_its_tool_carries_the_plugin_and_its_minimum_role(self, echo):
        spec = echo.registry.get("echo")
        assert (spec.source, spec.min_role) == ("_echo", "viewer")

    def test_it_is_subscribed_to_every_hook_the_core_fires(self, echo):
        assert {h: echo.bus.subscribers(h) for h in HOOKS} == {h: ["_echo"] for h in HOOKS}


class TestItsToolSeesTheRequest:
    async def test_a_call_reaches_every_service_in_the_requests_scope(self, echo):
        reply = await echo.chat({"text": "hello"}, RequestCaller("u", "viewer"))
        assert reply == {"prefix": "echo", "text": "hello", "role": "viewer", "may_edit": False,
                         "found": ["a.md"], "dimensions": 4}
        assert echo.processor.calls == [{"query": "hello", "top_k": 3, "scope": "ws-a",
                                         "knowledge_scope": "local"}]

    async def test_identity_reports_the_role_the_guard_recorded(self, echo):
        """Over-correction guard for the viewer above: an editor is told it may edit."""
        reply = await echo.chat({"text": "hello"}, RequestCaller("u", "editor"))
        assert (reply["role"], reply["may_edit"]) == ("editor", True)

    async def test_a_setting_from_the_environment_replaces_its_default(self, monkeypatch):
        monkeypatch.setenv("PLUGIN__ECHO_PREFIX", "custom")
        loaded = _Echo(monkeypatch)
        try:
            reply = await loaded.chat({"text": "hello"}, RequestCaller("u", "viewer"))
        finally:
            loaded.loader.unload("_echo")
        assert reply["prefix"] == "custom"

    async def test_a_workspace_api_key_is_refused_the_global_tier(self, echo):
        reply = await echo.chat({"text": "hello", "knowledge_scope": "global"},
                                RequestCaller(None, "owner", via_api_key=True))
        assert (reply, echo.processor.calls) == (
            "Tool error: the global knowledge tier is not open to this caller", [])

    async def test_its_own_call_is_announced_to_it(self, echo):
        await echo.chat({"text": "hello"}, RequestCaller("u", "viewer"))
        assert echo.module.received == [("on_tool_invocation", {"tool": "echo", "source": "_echo"})]


class TestItReceivesEveryHook:
    def test_each_payload_arrives_in_order(self, echo):
        ingested = {"document_id": 1, "filename": "a.md", "workspace_id": "ws-a",
                    "chunks": 2, "replaced": False, "source_id": None}
        tick = {"tick": 1, "at": "2026-11-15T00:00:00+00:00"}
        echo.bus.emit("on_document_ingested", ingested)
        echo.bus.emit("on_scheduler_tick", tick)
        assert echo.module.received == [("on_document_ingested", ingested),
                                        ("on_scheduler_tick", tick)]


class TestUnloadingEndsIt:
    def test_unloading_removes_its_tool_and_every_subscription(self, monkeypatch):
        loaded = _Echo(monkeypatch)
        loaded.loader.unload("_echo")
        assert ("echo" in loaded.registry, [loaded.bus.subscribers(h) for h in HOOKS]) == (
            False, [[] for _ in HOOKS])
