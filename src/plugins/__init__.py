"""The plugin contract's core side: the manifest and the services a plugin receives (PC-1)."""

from __future__ import annotations

from typing import Any

from .. import config
from ..tools.registry import ToolRegistry
from .hooks import HOOKS
from .manifest import (
    SCOPES,
    ConfigValue,
    Manifest,
    ManifestError,
    parse_setting,
    read_manifest,
)
from .services import (
    ConfigHandle,
    IdentityHandle,
    LlmHandle,
    PluginServices,
    RetrievalHandle,
    ToolsHandle,
)


def build_services(
    name: str,
    manifest: Manifest,
    registry: ToolRegistry,
    *,
    processor: Any = None,  # Any: DocumentProcessor; the singleton unless a test passes one
    client: Any = None,  # Any: OllamaClient; likewise
) -> PluginServices:
    """Assemble the handles for plugin *name*. ManifestError when a setting does not parse."""
    values: dict[str, ConfigValue] = {}
    for key, (type_name, default) in manifest.config.items():
        raw = config.plugin_setting(name, key)
        try:
            values[key] = default if raw is None else parse_setting(raw, type_name)
        except ManifestError as exc:
            raise ManifestError(f"setting {key}: {exc}") from exc

    if processor is None:
        from ..rag import doc_processor as processor
    if client is None:
        from ..ollama_client import ollama_client as client

    return PluginServices(
        name=name,
        manifest=manifest,
        config=ConfigHandle(values),
        llm=LlmHandle(client),
        retrieval=RetrievalHandle(processor, manifest.scope),
        identity=IdentityHandle(),
        tools=ToolsHandle(registry, source=name, min_role=manifest.min_role),
    )


__all__ = [
    "HOOKS",
    "SCOPES",
    "ConfigHandle",
    "IdentityHandle",
    "LlmHandle",
    "Manifest",
    "ManifestError",
    "PluginServices",
    "RetrievalHandle",
    "ToolsHandle",
    "build_services",
    "read_manifest",
]
