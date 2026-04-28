"""
Plugin Loader
=============

Dynamically loads tool plugins from a directory. Each plugin is a plain
``.py`` file that registers tools via the ``@tool_registry.register``
decorator — exactly like the built-in tools, but discovered at runtime
without touching application source code.

Plugin contract
---------------
A plugin file **must** be importable as a top-level Python module (i.e. it
can use absolute imports such as ``from src.tools.registry import
tool_registry``).  The only required content is at least one
``@tool_registry.register`` decorated function.

Optionally, a plugin can declare metadata at module level::

    PLUGIN_META = {
        "name": "My Plugin",
        "version": "1.0.0",
        "author": "Jane Doe",
        "description": "Short description shown in /api/plugins.",
    }

Usage
-----
The application creates a single ``plugin_loader`` singleton and calls
``load_all()`` once at startup::

    from src.tools import plugin_loader
    plugin_loader.load_all(Path("plugins"))

Individual plugins can also be loaded, unloaded, or hot-reloaded at
runtime (e.g. from an admin endpoint) without restarting the process.

"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path
from typing import Any

from ..utils.logging_config import get_logger
from .registry import ToolRegistry, tool_registry

logger = get_logger(__name__)


class PluginLoader:
    """
    Scans a directory for ``.py`` plugin files and dynamically imports them.

    Each loaded plugin's tools are tracked so they can be individually
    unloaded or hot-reloaded without restarting the server.

    Args:
        registry: ``ToolRegistry`` instance to register tools into.
                  Defaults to the module-level ``tool_registry`` singleton.
    """

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry or tool_registry
        # plugin_stem -> {"path": str, "tools": [name, ...], "meta": {...}, "error": str|None}
        self._plugins: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(self, plugins_dir: Path) -> int:
        """
        Scan *plugins_dir* and import every ``.py`` file that does not start
        with an underscore.

        Args:
            plugins_dir: Directory to scan.

        Returns:
            Number of plugin files successfully loaded.
        """
        plugins_dir = Path(plugins_dir)
        if not plugins_dir.exists():
            logger.debug(f"[PLUGINS] Directory does not exist: {plugins_dir}")
            return 0

        loaded = 0
        for path in sorted(plugins_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                self.load_file(path)
                loaded += 1
            except Exception as exc:
                plugin_key = path.stem
                logger.error(
                    f"[PLUGINS] Failed to load '{plugin_key}': {exc}",
                    exc_info=True,
                )
                self._plugins[plugin_key] = {
                    "path": str(path),
                    "tools": [],
                    "meta": {},
                    "error": str(exc),
                }

        logger.info(f"[PLUGINS] Loaded {loaded} plugin(s) from {plugins_dir}")
        return loaded

    def load_file(self, path: Path) -> list[str]:
        """
        Dynamically import a single plugin file.

        Any ``@tool_registry.register`` calls in the file execute during
        import, registering the tools under their declared names.  The
        loader then tags each new tool with the plugin's stem name as its
        ``source`` so it can be tracked and unloaded later.

        Args:
            path: Path to the ``.py`` plugin file.

        Returns:
            List of tool names newly registered by this plugin.

        Raises:
            ImportError: If the module spec cannot be created.
            Exception:   Any exception raised during module execution.
        """
        path = Path(path).resolve()
        plugin_key = path.stem

        # Snapshot existing tools before loading
        before: set = set(self._registry.names)

        # If reloading, cleanly remove the previous version first
        if plugin_key in self._plugins:
            self._unload_tools(plugin_key)

        # Ensure the repo root is on sys.path so plugins can do
        # ``from src.tools.registry import tool_registry``
        repo_root = str(path.parent.parent)
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)

        module_name = f"localchat_plugin_{plugin_key}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception:
            sys.modules.pop(module_name, None)
            raise

        # Determine which tools this plugin registered
        after: set = set(self._registry.names)
        new_tools = sorted(after - before)

        # Re-tag each new tool with the plugin stem as its source
        for tool_name in new_tools:
            existing = self._registry.get(tool_name)
            if existing is not None:
                self._registry._tools[tool_name] = dataclasses.replace(
                    existing, source=plugin_key
                )

        # Read optional PLUGIN_META
        meta = getattr(module, "PLUGIN_META", {})
        if not isinstance(meta, dict):
            meta = {}

        self._plugins[plugin_key] = {
            "path": str(path),
            "tools": new_tools,
            "meta": meta,
            "error": None,
        }

        logger.info(
            f"[PLUGINS] Loaded '{plugin_key}': "
            f"{len(new_tools)} tool(s) → {new_tools}"
        )
        return new_tools

    def unload(self, plugin_name: str) -> bool:
        """
        Unregister all tools contributed by *plugin_name* and remove it
        from the loaded-plugin index.

        Args:
            plugin_name: Plugin stem name (filename without ``.py``).

        Returns:
            ``True`` if the plugin was found and unloaded, ``False`` otherwise.
        """
        if plugin_name not in self._plugins:
            return False
        self._unload_tools(plugin_name)
        del self._plugins[plugin_name]
        logger.info(f"[PLUGINS] Unloaded plugin '{plugin_name}'")
        return True

    def reload(self, plugin_name: str) -> list[str]:
        """
        Unload then re-import a plugin, picking up any file changes.

        Args:
            plugin_name: Plugin stem name.

        Returns:
            List of tool names registered after reload.

        Raises:
            KeyError: If the plugin is not currently loaded.
        """
        info = self._plugins.get(plugin_name)
        if info is None:
            raise KeyError(f"Plugin not loaded: {plugin_name!r}")
        path = Path(info["path"])
        logger.info(f"[PLUGINS] Reloading '{plugin_name}'")
        return self.load_file(path)

    def reload_all(self) -> int:
        """
        Reload every currently loaded plugin from disk.

        Returns:
            Number of plugins successfully reloaded.
        """
        count = 0
        plugin_names = list(self._plugins)  # snapshot — reload() mutates self._plugins
        for plugin_name in plugin_names:
            try:
                self.reload(plugin_name)
                count += 1
            except Exception as exc:
                logger.error(
                    f"[PLUGINS] Reload failed for '{plugin_name}': {exc}",
                    exc_info=True,
                )
        logger.info(f"[PLUGINS] Reloaded {count} plugin(s)")
        return count

    def list_plugins(self) -> list[dict[str, Any]]:
        """
        Return metadata for every loaded plugin.

        Each entry contains:

        * ``name``       — plugin stem
        * ``path``       — absolute path to the file
        * ``tools``      — list of tool names it registered
        * ``tool_count`` — ``len(tools)``
        * ``meta``       — contents of ``PLUGIN_META`` (may be ``{}``)
        * ``error``      — load error message, or ``None`` on success
        """
        return [
            {
                "name": key,
                "path": info["path"],
                "tools": info["tools"],
                "tool_count": len(info["tools"]),
                "meta": info["meta"],
                "error": info["error"],
            }
            for key, info in self._plugins.items()
        ]

    @property
    def loaded_count(self) -> int:
        """Number of plugin files currently loaded (including errored ones)."""
        return len(self._plugins)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _unload_tools(self, plugin_name: str) -> None:
        """Remove all tools registered by *plugin_name* from the registry."""
        tools = self._plugins.get(plugin_name, {}).get("tools", [])
        for tool_name in tools:
            self._registry.unregister(tool_name)
        # Evict the cached module so a future reload re-executes the file
        sys.modules.pop(f"localchat_plugin_{plugin_name}", None)
