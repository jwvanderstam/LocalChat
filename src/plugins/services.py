"""The capabilities a plugin is handed at load time (PC-1).

A plugin defines ``setup(services)`` and reaches the core only through the handles on
:class:`PluginServices`. It never imports ``src``. Each handle is named for what it does,
not for any plugin that uses it (`.claude/rules/plugins.md`).

What a handle cannot do matters as much as what it can:

* ``retrieval`` reads the workspace the request was authorised for. It takes no
  workspace argument, so a plugin cannot point a search at a workspace the caller was
  never admitted to (P0-1, P0-2).
* ``identity`` only reads. Whether the caller may use a plugin's tools at all is the
  core's decision, made from ``PLUGIN_MIN_ROLE`` before the tool runs.
* There is no ``storage`` handle and no ``llm.complete`` yet. Both wait for a consumer
  that needs them; see the status banner in `.claude/rules/plugins.md`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..rag.retrieval import KnowledgeScope
from ..tools.registry import ToolRegistry
from ..utils.caller import RequestCaller, caller_has_role, current_request_caller
from ..utils.logging_config import get_logger
from ..utils.scope import current_request_scope
from .manifest import ConfigValue, Manifest

logger = get_logger(__name__)

#: The tiers each PLUGIN_SCOPE may ask for.
_REACH: dict[str, frozenset[str]] = {
    "local": frozenset({"local"}),
    "global": frozenset({"global"}),
    "hybrid": frozenset({"local", "global", "hybrid"}),
}


class ConfigHandle:
    """The plugin's own declared settings, typed, with their defaults applied."""

    def __init__(self, values: dict[str, ConfigValue]) -> None:
        self._values = dict(values)

    def get(self, key: str) -> ConfigValue:
        """The value of a key the manifest declared; KeyError for one it did not."""
        if key not in self._values:
            raise KeyError(f"{key!r} is not declared in PLUGIN_CONFIG")
        return self._values[key]

    def as_dict(self) -> dict[str, ConfigValue]:
        return dict(self._values)


class LlmHandle:
    """Embeddings from the core's model server."""

    def __init__(self, client: Any) -> None:  # Any: OllamaClient, imported lazily by the loader
        self._client = client

    def embed(self, text: str) -> list[float]:
        """The embedding the core would store for *text*; RuntimeError when none can be made."""
        model = self._client.get_embedding_model()
        if not model:
            raise RuntimeError("no embedding model is available")
        ok, vector = self._client.generate_embedding(model, text)
        if not ok:
            raise RuntimeError("the embedding could not be generated")
        return list(vector)


class RetrievalHandle:
    """Search the documents the current request may read."""

    def __init__(self, processor: Any, reach: str) -> None:  # Any: DocumentProcessor, lazily imported
        self._processor = processor
        self._allowed = _REACH[reach]

    def retrieve(
        self, query: str, knowledge_scope: KnowledgeScope = "local", top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Ranked chunks for *query*, from the request's workspace and the tiers allowed.

        PermissionError for a tier beyond the manifest's PLUGIN_SCOPE, or any tier but
        ``local`` for a workspace API key, refused rather than narrowed as GKB-3 does:
        a narrowed answer could be taken for the one asked for.
        """
        if knowledge_scope not in self._allowed:
            raise PermissionError(f"PLUGIN_SCOPE does not reach the {knowledge_scope!r} tier")
        caller = current_request_caller()
        if knowledge_scope != "local" and (caller is None or caller.via_api_key):
            raise PermissionError("the global knowledge tier is not open to this caller")
        results = self._processor.retrieve_context(
            query, top_k=top_k, scope=current_request_scope(), knowledge_scope=knowledge_scope,
        )
        return [
            {
                "text": r.chunk_text,
                "filename": r.filename,
                "chunk_index": r.chunk_index,
                "similarity": r.similarity,
                "tier": r.metadata.get("knowledge_tier", "local"),
            }
            for r in results
        ]


class IdentityHandle:
    """Who the current request is from. Read only."""

    def current(self) -> RequestCaller | None:
        """The caller, or None outside a request."""
        return current_request_caller()

    def has_role(self, min_role: str) -> bool:
        """True when the caller is at least *min_role*: viewer < editor < owner < admin."""
        return caller_has_role(min_role)


class ToolsHandle:
    """Register LLM-callable tools, tagged with this plugin and its minimum role."""

    def __init__(self, registry: ToolRegistry, source: str, min_role: str) -> None:
        self._registry = registry
        self._source = source
        self._min_role = min_role
        self._closed = False

    def close(self) -> None:
        """Refuse registration from now on; the loader calls this when ``setup()`` returns."""
        self._closed = True

    def register(
        self, name: str, description: str, parameters: dict[str, Any],
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator, as ``tool_registry.register``. A name already taken is refused.

        Refused rather than overwritten: a plugin replacing ``search_documents`` would
        decide what every chat's document search returns.
        """
        if self._closed:
            raise RuntimeError("tools are registered in setup(); this handle is closed")
        if name in self._registry:
            raise ValueError(f"tool {name!r} is already registered")
        return self._registry.register(
            name=name, description=description, parameters=parameters,
            source=self._source, min_role=self._min_role,
        )


@dataclass(frozen=True)
class PluginServices:
    """Everything a plugin may ask the core for, handed to its ``setup()``."""

    name: str
    manifest: Manifest
    config: ConfigHandle
    llm: LlmHandle
    retrieval: RetrievalHandle
    identity: IdentityHandle
    tools: ToolsHandle
