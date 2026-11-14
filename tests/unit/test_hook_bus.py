"""PC-2 — the hook bus, the core scheduler, and the three places the core emits.

The core announces; a plugin reacts. A subscriber that raises is skipped and the core
operation completes as if there were none, and a plugin's subscriptions go with it when
it is unloaded or fails to load.
"""

from __future__ import annotations

import hashlib
import sys
import textwrap
import threading
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from src.plugins import ManifestError, read_manifest
from src.plugins.hooks import HOOKS, HookBus, Scheduler
from src.tools.executor import ToolExecutor
from src.tools.plugin_loader import PluginLoader
from src.tools.registry import ToolRegistry
from src.utils.caller import RequestCaller, request_caller

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# The bus
# ---------------------------------------------------------------------------

class TestHookBus:
    def test_emit_with_no_subscribers_calls_nothing_and_returns(self):
        bus = HookBus()
        bus.emit("on_document_ingested", {"document_id": 1})
        assert [bus.subscribers(h) for h in HOOKS] == [[], [], []]

    def test_a_raising_subscriber_is_skipped_and_the_next_still_runs(self):
        bus, seen = HookBus(), []

        def boom(payload):
            raise RuntimeError("plugin bug")

        bus.subscribe("on_document_ingested", "bad", boom)
        bus.subscribe("on_document_ingested", "good", lambda p: seen.append(p["document_id"]))
        bus.emit("on_document_ingested", {"document_id": 7})
        assert seen == [7]

    def test_each_subscriber_gets_its_own_copy_of_the_payload(self):
        bus, seen = HookBus(), []
        bus.subscribe("on_tool_invocation", "a", lambda p: p.update(tool="changed"))
        bus.subscribe("on_tool_invocation", "b", lambda p: seen.append(p["tool"]))
        payload = {"tool": "calculate"}
        bus.emit("on_tool_invocation", payload)
        assert (seen, payload) == (["calculate"], {"tool": "calculate"})

    def test_unsubscribe_removes_only_that_owners_subscribers(self):
        bus = HookBus()
        bus.subscribe("on_scheduler_tick", "a", lambda p: None)
        bus.subscribe("on_document_ingested", "a", lambda p: None)
        bus.subscribe("on_scheduler_tick", "b", lambda p: None)
        bus.unsubscribe("a")
        assert (bus.subscribers("on_scheduler_tick"), bus.subscribers("on_document_ingested")) == (
            ["b"], [])

    def test_subscribing_to_an_unknown_hook_is_refused(self):
        with pytest.raises(ValueError, match="unknown hook"):
            HookBus().subscribe("on_route_mount", "a", lambda p: None)

    def test_emitting_an_unknown_hook_is_refused(self):
        with pytest.raises(ValueError, match="unknown hook"):
            HookBus().emit("on_route_mount", {})


class TestScheduler:
    def test_ticks_are_numbered_and_stop_ends_them(self):
        bus, ticks, third = HookBus(), [], threading.Event()

        def record(payload):
            ticks.append(payload["tick"])
            if len(ticks) == 3:
                third.set()

        bus.subscribe("on_scheduler_tick", "t", record)
        scheduler = Scheduler(bus, 0.01)
        scheduler.start()
        assert third.wait(5)
        scheduler.stop()
        stopped_at = len(ticks)
        threading.Event().wait(0.05)
        assert (ticks[:3], len(ticks)) == ([1, 2, 3], stopped_at)


# ---------------------------------------------------------------------------
# The manifest and the loader
# ---------------------------------------------------------------------------

def test_a_declared_hook_without_its_function_is_refused():
    module = ModuleType("p")
    module.PLUGIN_HOOKS = ["on_document_ingested"]
    with pytest.raises(ManifestError, match="no function: on_document_ingested"):
        read_manifest(module)


def test_on_route_mount_is_not_in_the_catalogue_yet():
    module = ModuleType("p")
    module.PLUGIN_HOOKS = ["on_route_mount"]
    module.on_route_mount = lambda payload: None
    with pytest.raises(ManifestError, match="unknown hook"):
        read_manifest(module)


_SUBSCRIBER = '''
PLUGIN_HOOKS = ["on_document_ingested"]
SEEN = []

def on_document_ingested(payload):
    SEEN.append(payload["document_id"])

def setup(services):
    pass
'''


def _loader(tmp_path: Path, body: str = _SUBSCRIBER) -> tuple[PluginLoader, HookBus]:
    (tmp_path / "listener.py").write_text(textwrap.dedent(body), encoding="utf-8")
    bus = HookBus()
    return PluginLoader(registry=ToolRegistry(), bus=bus), bus


class TestLoaderSubscribes:
    def test_a_loaded_plugin_receives_the_hook_it_declared(self, tmp_path):
        loader, bus = _loader(tmp_path)
        loader.load_all(tmp_path)
        bus.emit("on_document_ingested", {"document_id": 5})
        seen = sys.modules["localchat_plugin_listener"].SEEN
        loader.unload("listener")
        assert seen == [5]

    def test_unload_removes_the_subscription(self, tmp_path):
        loader, bus = _loader(tmp_path)
        loader.load_all(tmp_path)
        loader.unload("listener")
        assert bus.subscribers("on_document_ingested") == []

    def test_reload_leaves_one_subscription_not_two(self, tmp_path):
        loader, bus = _loader(tmp_path)
        loader.load_all(tmp_path)
        loader.reload("listener")
        owners = bus.subscribers("on_document_ingested")
        loader.unload("listener")
        assert owners == ["listener"]

    def test_a_plugin_whose_setup_fails_is_not_subscribed(self, tmp_path):
        loader, bus = _loader(tmp_path, _SUBSCRIBER.replace("    pass", "    raise RuntimeError('no')"))
        assert (loader.load_all(tmp_path), bus.subscribers("on_document_ingested")) == (0, [])


# ---------------------------------------------------------------------------
# Where the core emits
# ---------------------------------------------------------------------------

def _processor(embedding_model: str | None = "embed", existing: dict | None = None):
    from src.rag.processor import DocumentProcessor

    processor = DocumentProcessor(db=MagicMock(), ollama_client=MagicMock())
    processor._db.documents.exists.return_value = (True, existing) if existing else (False, {})
    processor._db.documents.insert.return_value = 42
    processor._ollama_client.get_embedding_model.return_value = embedding_model
    return processor


def _ingest(processor, path: Path) -> tuple[tuple, list[dict]]:
    path.write_text("content", encoding="utf-8")
    bus, seen = HookBus(), []
    bus.subscribe("on_document_ingested", "t", seen.append)
    with (
        patch("src.rag.processor.hook_bus", bus),
        patch("src.rag.processor._compute_file_hash", return_value=hashlib.sha256(b"new").hexdigest()),
        patch.object(processor, "_load_document_chunks",
                     return_value=(True, None, [{"text": "a", "metadata": {}}] * 2, "content", "TXT", "v1")),
        patch.object(processor, "_run_embedding_pipeline",
                     return_value=([{"chunk_text": "a"}, {"chunk_text": "b"}], 0)),
    ):
        result = processor.ingest_document(str(path), workspace_id="ws-1", source_id="src-1")
    return result, seen


class TestDocumentIngestedIsEmitted:
    def test_a_new_document_is_announced_once_with_its_id_and_workspace(self, tmp_path):
        (ok, _, doc_id), seen = _ingest(_processor(), tmp_path / "report.txt")
        assert (ok, doc_id, seen) == (True, 42, [{
            "document_id": 42, "filename": "report.txt", "workspace_id": "ws-1",
            "chunks": 2, "replaced": False, "source_id": "src-1",
        }])

    def test_a_replaced_document_is_announced_as_replaced_under_its_own_id(self, tmp_path):
        processor = _processor(existing={"id": 9, "content_hash": "old"})
        (ok, _, doc_id), seen = _ingest(processor, tmp_path / "report.txt")
        assert (ok, doc_id, [(e["document_id"], e["replaced"]) for e in seen]) == (True, 9, [(9, True)])

    def test_a_failed_ingest_announces_nothing(self, tmp_path):
        (ok, _, _), seen = _ingest(_processor(embedding_model=None), tmp_path / "report.txt")
        assert (ok, seen) == (False, [])


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register("open_tool", "anyone", {"type": "object", "properties": {}})(lambda: "open")
    reg.register("owner_tool", "owners", {"type": "object", "properties": {}},
                 source="gated", min_role="owner")(lambda: "secret")
    return reg


async def _announced(calls: list[str], role: str) -> list[dict]:
    replies = iter([
        {"message": {"content": "", "tool_calls": [
            {"function": {"name": n, "arguments": {}}} for n in calls]}},
        {"message": {"content": "done"}},
    ])

    async def completion(model, messages, tools=None):
        return next(replies)

    client = MagicMock()
    client.generate_chat_completion = completion
    bus, seen = HookBus(), []
    bus.subscribe("on_tool_invocation", "t", seen.append)
    with patch("src.tools.executor.hook_bus", bus), request_caller(RequestCaller("u", role)):
        out = [c async for c in ToolExecutor(client, _registry()).execute(
            "m", [{"role": "user", "content": "hi"}])]
    if "".join(out) != "done":
        raise AssertionError(f"the tool loop did not finish: {out!r}")
    return seen


class TestToolInvocationIsEmitted:
    async def test_each_tool_that_ran_is_announced_with_its_source(self):
        seen = await _announced(["open_tool", "owner_tool"], "owner")
        assert seen == [{"tool": "open_tool", "source": "builtin"},
                        {"tool": "owner_tool", "source": "gated"}]

    async def test_a_refused_or_unknown_tool_is_not_announced(self):
        seen = await _announced(["owner_tool", "no_such_tool", "open_tool"], "editor")
        assert seen == [{"tool": "open_tool", "source": "builtin"}]
