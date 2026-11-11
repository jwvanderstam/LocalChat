"""PC-1 — the plugin contract's core side: manifest, services, and the role gate on tools.

Every plugin file here is written into a temporary directory, never read from
``plugins/``: the ``core-without-plugins`` job deletes that directory, and the contract
has to hold without it.
"""

from __future__ import annotations

import textwrap
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.plugins import (
    ManifestError,
    RetrievalHandle,
    ToolsHandle,
    build_services,
    read_manifest,
)
from src.plugins.manifest import parse_setting
from src.plugins.services import ConfigHandle, IdentityHandle, LlmHandle
from src.security_fastapi import check_workspace_access, create_access_token
from src.tools.executor import ToolExecutor
from src.tools.plugin_loader import PluginLoader
from src.tools.registry import ToolRegistry
from src.utils.caller import RequestCaller, caller_has_role, request_caller
from src.utils.scope import ScopeUnavailableError, request_scope
from src.utils.workspace import get_caller

pytestmark = pytest.mark.unit


def _module(**names: Any) -> ModuleType:
    mod = ModuleType("plugin_under_test")
    for k, v in names.items():
        setattr(mod, k, v)
    return mod


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class TestRoleLadder:
    def test_an_editor_meets_editor_but_not_owner(self):
        editor = RequestCaller(user_id="u", role="editor")
        assert (editor.has_role("viewer"), editor.has_role("editor"), editor.has_role("owner")) == (
            True, True, False,
        )

    def test_a_global_admin_meets_every_workspace_role(self):
        admin = RequestCaller(user_id="u", role="admin")
        assert all(admin.has_role(r) for r in ("viewer", "editor", "owner", "admin"))

    def test_an_owner_does_not_meet_admin(self):
        assert RequestCaller(user_id="u", role="owner").has_role("admin") is False

    def test_an_unknown_caller_role_meets_nothing(self):
        assert RequestCaller(user_id="u", role="wizard").has_role("viewer") is False

    def test_an_unknown_minimum_is_never_met(self):
        """A typo in a minimum must lock the tool, not open it."""
        assert RequestCaller(user_id="u", role="admin").has_role("superuser") is False

    def test_with_no_caller_bound_only_viewer_is_met(self):
        assert (caller_has_role("viewer"), caller_has_role("editor")) == (True, False)


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

class TestManifest:
    def test_an_empty_manifest_takes_every_default(self):
        m = read_manifest(_module())
        assert (m.scope, m.min_role, m.hooks, m.config) == ("local", "viewer", (), {})

    def test_declared_values_are_kept(self):
        m = read_manifest(_module(
            PLUGIN_SCOPE="hybrid", PLUGIN_MIN_ROLE="owner",
            PLUGIN_HOOKS=["on_scheduler_tick"], PLUGIN_CONFIG={"LIMIT": ("int", 3)},
        ))
        assert (m.scope, m.min_role, m.hooks, m.config) == (
            "hybrid", "owner", ("on_scheduler_tick",), {"LIMIT": ("int", 3)},
        )

    @pytest.mark.parametrize("names, fragment", [
        ({"PLUGIN_SCOPE": "everywhere"}, "PLUGIN_SCOPE"),
        ({"PLUGIN_MIN_ROLE": "user"}, "PLUGIN_MIN_ROLE"),
        ({"PLUGIN_CONTRIBUTES": True}, "PLUGIN_CONTRIBUTES"),
        ({"PLUGIN_HOOKS": "on_scheduler_tick"}, "PLUGIN_HOOKS must be a list"),
        ({"PLUGIN_HOOKS": ["on_everything"]}, "unknown hook"),
        ({"PLUGIN_CONFIG": [("LIMIT", "int", 3)]}, "must be a dict"),
        ({"PLUGIN_CONFIG": {"limit": ("int", 3)}}, "UPPER_SNAKE_CASE"),
        ({"PLUGIN_CONFIG": {"LIMIT": ("decimal", 3)}}, "(type, default)"),
        ({"PLUGIN_CONFIG": {"LIMIT": ("int", "3")}}, "is not a int"),
        ({"PLUGIN_CONFIG": {"LIMIT": ("int", True)}}, "is not a int"),
        ({"PLUGIN_CONFIG": {"ON": ("bool", 1)}}, "is not a bool"),
    ])
    def test_a_malformed_manifest_is_refused_naming_the_field(self, names, fragment):
        with pytest.raises(ManifestError, match=__import__("re").escape(fragment)):
            read_manifest(_module(**names))

    def test_a_float_setting_accepts_an_integer_default(self):
        assert read_manifest(_module(PLUGIN_CONFIG={"T": ("float", 1)})).config == {"T": ("float", 1)}

    @pytest.mark.parametrize("raw, type_name, expected", [
        ("yes", "bool", True), ("0", "bool", False), ("42", "int", 42),
        ("0.25", "float", 0.25), ("plain", "str", "plain"),
    ])
    def test_a_setting_is_typed(self, raw, type_name, expected):
        assert parse_setting(raw, type_name) == expected

    @pytest.mark.parametrize("raw, type_name", [("maybe", "bool"), ("4.5", "int"), ("x", "float")])
    def test_a_setting_that_does_not_parse_is_refused(self, raw, type_name):
        with pytest.raises(ManifestError):
            parse_setting(raw, type_name)


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

def _services(name: str = "my-plugin", **manifest: Any):
    return build_services(
        name, read_manifest(_module(**manifest)), ToolRegistry(),
        processor=MagicMock(), client=MagicMock(),
    )


class TestConfigHandle:
    def test_an_unset_key_takes_its_default(self, monkeypatch):
        monkeypatch.delenv("PLUGIN_MY_PLUGIN_LIMIT", raising=False)
        assert _services(PLUGIN_CONFIG={"LIMIT": ("int", 3)}).config.get("LIMIT") == 3

    def test_the_environment_overrides_the_default_typed(self, monkeypatch):
        """The plugin's stem is upper-cased and its dash made an underscore."""
        monkeypatch.setenv("PLUGIN_MY_PLUGIN_LIMIT", "7")
        assert _services(PLUGIN_CONFIG={"LIMIT": ("int", 3)}).config.get("LIMIT") == 7

    def test_a_value_that_does_not_parse_refuses_the_plugin(self, monkeypatch):
        monkeypatch.setenv("PLUGIN_MY_PLUGIN_LIMIT", "seven")
        with pytest.raises(ManifestError, match="setting LIMIT"):
            _services(PLUGIN_CONFIG={"LIMIT": ("int", 3)})

    def test_an_undeclared_key_is_a_key_error(self):
        with pytest.raises(KeyError):
            ConfigHandle({"A": 1}).get("B")


class _FakeProcessor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def retrieve_context(self, query: str, **kwargs: Any) -> list[Any]:
        self.calls.append({"query": query, **kwargs})
        return [SimpleNamespace(
            chunk_text="body", filename="a.md", chunk_index=2, similarity=0.9,
            metadata={"knowledge_tier": "global"}, chunk_id=11,
        )]


class TestRetrievalHandle:
    def test_it_searches_the_workspace_the_request_was_authorised_for(self):
        proc = _FakeProcessor()
        with request_scope("ws-a"), request_caller(RequestCaller("u", "viewer")):
            out = RetrievalHandle(proc, "local").retrieve("q", top_k=3)
        assert proc.calls == [{"query": "q", "top_k": 3, "scope": "ws-a", "knowledge_scope": "local"}]
        assert out == [{"text": "body", "filename": "a.md", "chunk_index": 2,
                        "similarity": 0.9, "tier": "global"}]

    def test_with_no_request_scope_it_refuses_rather_than_searching_everything(self):
        proc = _FakeProcessor()
        with pytest.raises(ScopeUnavailableError):
            RetrievalHandle(proc, "local").retrieve("q")
        assert proc.calls == []

    def test_a_tier_beyond_the_manifest_scope_is_refused(self):
        proc = _FakeProcessor()
        with request_scope("ws-a"), request_caller(RequestCaller("u", "admin")):
            with pytest.raises(PermissionError, match="PLUGIN_SCOPE"):
                RetrievalHandle(proc, "local").retrieve("q", knowledge_scope="global")
        assert proc.calls == []

    def test_a_workspace_api_key_is_refused_the_global_tier(self):
        proc = _FakeProcessor()
        with request_scope("ws-a"), request_caller(RequestCaller(None, "owner", via_api_key=True)):
            with pytest.raises(PermissionError, match="not open"):
                RetrievalHandle(proc, "hybrid").retrieve("q", knowledge_scope="hybrid")
        assert proc.calls == []

    def test_a_user_within_the_manifest_scope_reaches_the_global_tier(self):
        """Over-correction guard: the refusal above is about the key, not the tier."""
        proc = _FakeProcessor()
        with request_scope("ws-a"), request_caller(RequestCaller("u", "viewer")):
            RetrievalHandle(proc, "hybrid").retrieve("q", knowledge_scope="hybrid")
        assert proc.calls[0]["knowledge_scope"] == "hybrid"


class TestLlmHandle:
    def test_embed_returns_the_vector(self):
        client = MagicMock()
        client.get_embedding_model.return_value = "nomic"
        client.generate_embedding.return_value = (True, [0.1, 0.2])
        assert LlmHandle(client).embed("hi") == [0.1, 0.2]
        client.generate_embedding.assert_called_once_with("nomic", "hi")

    def test_a_failed_embedding_raises_rather_than_returning_empty(self):
        client = MagicMock()
        client.get_embedding_model.return_value = "nomic"
        client.generate_embedding.return_value = (False, [])
        with pytest.raises(RuntimeError):
            LlmHandle(client).embed("hi")


class TestIdentityHandle:
    def test_it_reads_the_bound_caller(self):
        caller = RequestCaller("u-1", "editor")
        with request_caller(caller):
            handle = IdentityHandle()
            assert (handle.current(), handle.has_role("editor"), handle.has_role("owner")) == (
                caller, True, False,
            )


class TestToolsHandle:
    def test_a_tool_carries_the_plugin_and_its_minimum_role(self):
        reg = ToolRegistry()
        ToolsHandle(reg, source="p", min_role="owner").register("t", "d", {"type": "object"})(lambda: "x")
        spec = reg.get("t")
        assert (spec.source, spec.min_role) == ("p", "owner")

    def test_a_name_already_taken_is_refused_and_the_original_kept(self):
        reg = ToolRegistry()
        reg.register("search_documents", "core", {"type": "object"})(lambda: "core")
        with pytest.raises(ValueError, match="already registered"):
            ToolsHandle(reg, source="p", min_role="viewer").register("search_documents", "d", {})
        assert reg.get("search_documents").handler() == "core"


# ---------------------------------------------------------------------------
# The executor's role gate
# ---------------------------------------------------------------------------

def _gated_registry(calls: list[str]) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register("open_tool", "anyone", {"type": "object", "properties": {}})(
        lambda: calls.append("open_tool") or "open")
    reg.register("owner_tool", "owners", {"type": "object", "properties": {}}, min_role="owner")(
        lambda: calls.append("owner_tool") or "secret")
    return reg


class TestExecutorRoleGate:
    async def test_a_tool_above_the_callers_role_is_not_offered(self):
        offered: list[list[str]] = []

        async def completion(model, messages, tools=None):
            offered.append([t["function"]["name"] for t in tools or []])
            return {"message": {"content": "done"}}

        client = MagicMock()
        client.generate_chat_completion = completion
        executor = ToolExecutor(client, _gated_registry([]))
        with request_caller(RequestCaller("u", "editor")):
            _ = [c async for c in executor.execute("m", [{"role": "user", "content": "hi"}])]
        assert offered == [["open_tool"]]

    def test_a_tool_called_below_its_role_is_refused_as_unknown(self):
        calls: list[str] = []
        executor = ToolExecutor(MagicMock(), _gated_registry(calls))
        with request_caller(RequestCaller("u", "editor")):
            result = executor._run_tool("owner_tool", {})
        assert (result, calls) == ("Unknown tool: owner_tool", [])

    def test_a_tool_called_at_its_role_runs(self):
        calls: list[str] = []
        executor = ToolExecutor(MagicMock(), _gated_registry(calls))
        with request_caller(RequestCaller("u", "owner")):
            result = executor._run_tool("owner_tool", {})
        assert (result, calls) == ("secret", ["owner_tool"])

    def test_with_no_caller_a_viewer_tool_still_runs(self):
        calls: list[str] = []
        assert ToolExecutor(MagicMock(), _gated_registry(calls))._run_tool("open_tool", {}) == "open"


# ---------------------------------------------------------------------------
# The loader
# ---------------------------------------------------------------------------

_CONTRACT = '''
PLUGIN_MIN_ROLE = "editor"
PLUGIN_CONFIG = {"GREETING": ("str", "hello")}

def setup(services):
    greeting = services.config.get("GREETING")

    @services.tools.register(name="greet", description="d", parameters={"type": "object"})
    def greet():
        return greeting
'''

_LEGACY = '''
from src.tools.registry import tool_registry

@tool_registry.register(name="legacy_tool", description="d", parameters={"type": "object"})
def legacy_tool():
    return "old"
'''


def _write(directory, name: str, body: str) -> None:
    (directory / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")


class TestLoader:
    def test_a_contract_plugin_registers_through_setup_with_its_manifest(self, tmp_path):
        _write(tmp_path, "greeter", _CONTRACT)
        reg = ToolRegistry()
        loader = PluginLoader(registry=reg)
        assert loader.load_all(tmp_path) == 1
        [info] = loader.list_plugins()
        spec = reg.get("greet")
        assert (info["legacy"], info["manifest"]["min_role"], info["tools"]) == (False, "editor", ["greet"])
        assert (spec.source, spec.min_role, spec.handler()) == ("greeter", "editor", "hello")

    def test_a_malformed_manifest_disables_only_that_plugin(self, tmp_path):
        _write(tmp_path, "bad", 'PLUGIN_SCOPE = "everywhere"\ndef setup(services):\n    pass\n')
        _write(tmp_path, "greeter", _CONTRACT)
        reg = ToolRegistry()
        loader = PluginLoader(registry=reg)
        assert loader.load_all(tmp_path) == 1
        by_name = {p["name"]: p for p in loader.list_plugins()}
        assert "PLUGIN_SCOPE" in by_name["bad"]["error"]
        assert reg.names == ["greet"]

    def test_a_setup_that_fails_part_way_leaves_no_tool_behind(self, tmp_path):
        _write(tmp_path, "half", '''
def setup(services):
    services.tools.register(name="first", description="d", parameters={})(lambda: 1)
    raise RuntimeError("second tool failed")
''')
        reg = ToolRegistry()
        loader = PluginLoader(registry=reg)
        assert loader.load_all(tmp_path) == 0
        assert (reg.names, loader.list_plugins()[0]["error"]) == ([], "second tool failed")

    def test_a_plugin_without_setup_loads_as_legacy(self, tmp_path):
        from src.tools.registry import tool_registry

        _write(tmp_path, "oldstyle", _LEGACY)
        loader = PluginLoader(registry=tool_registry)
        try:
            loader.load_all(tmp_path)
            [info] = loader.list_plugins()
            assert (info["legacy"], info["manifest"], info["tools"]) == (True, None, ["legacy_tool"])
        finally:
            loader.unload("oldstyle")
        assert "legacy_tool" not in tool_registry

    def test_a_reload_still_records_the_plugins_tools(self, tmp_path):
        """The snapshot used to precede the unload, so a reload recorded no tools and a
        later unload left them registered."""
        _write(tmp_path, "greeter", _CONTRACT)
        reg = ToolRegistry()
        loader = PluginLoader(registry=reg)
        loader.load_all(tmp_path)
        assert loader.reload("greeter") == ["greet"]
        loader.unload("greeter")
        assert reg.names == []


# ---------------------------------------------------------------------------
# The guard records who it admitted
# ---------------------------------------------------------------------------

_USER = "88888888-8888-8888-8888-888888888888"


def _request(*, token: str | None = None, api_key: str | None = None, db: Any) -> MagicMock:
    req = MagicMock()
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if api_key:
        headers["X-API-Key"] = api_key
    req.headers.get = lambda k, default="": headers.get(k, default)
    req.cookies = {}
    req.app.state.db = db
    req.query_params = {}
    req.path_params = {}
    req.state = SimpleNamespace(resolved_workspace_id=None)
    return req


def _db(*, member_role: str | None = "editor", global_role: str | None = "user") -> MagicMock:
    db = MagicMock()
    db.is_connected = True
    db.members.role.return_value = member_role
    db.members.for_user.return_value = []
    db.workspaces.default_id.return_value = "ws-1"
    db.api_keys.resolve.return_value = ("ws-1", "viewer")
    db.tokens.is_revoked.return_value = False
    db.users.get_role.return_value = global_role
    return db


class TestGuardRecordsTheCaller:
    def test_a_member_is_recorded_with_their_workspace_role(self):
        req = _request(token=create_access_token(_USER, {"role": "user"}), db=_db(member_role="owner"))
        assert check_workspace_access(req, "ws-1", "viewer") is None
        assert get_caller(req) == RequestCaller(user_id=_USER, role="owner", via_api_key=False)

    def test_a_global_admin_is_recorded_as_admin(self):
        req = _request(token=create_access_token(_USER, {"role": "admin"}), db=_db(global_role="admin"))
        assert check_workspace_access(req, "ws-1", "viewer") is None
        assert get_caller(req) == RequestCaller(user_id=_USER, role="admin", via_api_key=False)

    def test_an_api_key_is_recorded_with_its_role_and_no_user(self):
        req = _request(api_key="lcw_abc", db=_db())
        assert check_workspace_access(req, "ws-1", "viewer") is None
        assert get_caller(req) == RequestCaller(user_id=None, role="viewer", via_api_key=True)

    def test_a_refused_caller_is_not_recorded(self):
        req = _request(token=create_access_token(_USER, {"role": "user"}), db=_db(member_role=None))
        assert check_workspace_access(req, "ws-1", "viewer") is not None
        assert get_caller(req) is None
