# LocalChat Plugin System

> Verified against `src/tools/`, `src/plugins/` and `src/app_bootstrap.py` on 2026-11-11.
> PC-1 of the contract in `.claude/rules/plugins.md` ships: the manifest and the services
> below. The hook bus (PC-2) and the `_echo` reference plugin (PC-3) do not exist yet.

Drop a `.py` file here — LocalChat loads it automatically at startup.

---

## How it works

1. On startup, `PluginLoader.load_all()` scans this directory for `*.py` files (skips `_`-prefixed files).
2. Each file is imported. If it defines `setup(services)`, the loader validates its manifest, builds its services and calls `setup`, where the plugin registers its tools.
3. The LLM can call your tools during chat just like the built-in ones (`search_documents`, `list_documents`, `calculate`, `get_current_datetime`). The tool loop runs only when retrieval found no document or web context for the question, and only with `TOOL_CALLING_ENABLED=true` (the default).

No source-code changes needed — just drop a file and restart (or call `POST /api/plugins/reload`).

---

## Plugin file contract

```python
# plugins/my_plugin.py — imports nothing from src

PLUGIN_META = {"name": "My Plugin", "version": "1.0.0", "description": "Shown in GET /api/plugins."}

# The manifest. Every name is optional; these are the defaults.
PLUGIN_SCOPE = "local"        # retrieval reach: local | global | hybrid
PLUGIN_MIN_ROLE = "viewer"    # who may use its tools: viewer | editor | owner | admin
PLUGIN_HOOKS = []             # validated against the catalogue; nothing fires them until PC-2
PLUGIN_CONFIG = {             # KEY: (type, default); type is str | int | float | bool
    "TOP_K": ("int", 5),
}


def setup(services):
    top_k = services.config.get("TOP_K")

    @services.tools.register(
        name="my_tool",                       # unique; a name already taken is refused
        description="What this tool does.",   # shown to the LLM
        parameters={"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
    )
    def my_tool(q: str) -> str:
        hits = services.retrieval.retrieve(q, top_k=top_k)
        return "\n".join(h["text"] for h in hits)
```

A malformed manifest, a setting that does not parse, or a `setup` that raises disables
**that plugin only**: the error shows in `GET /api/plugins`, any tool it registered before
failing is removed, and the application starts normally.

### The services

| Handle | What it does | What it cannot do |
|---|---|---|
| `services.tools.register(name, description, parameters)` | Registers a tool, tagged with this plugin and its `PLUGIN_MIN_ROLE` | Replace a tool that already exists |
| `services.retrieval.retrieve(query, knowledge_scope="local", top_k=5)` | Searches the documents the current request may read; returns `text`, `filename`, `chunk_index`, `similarity`, `tier` per chunk | Name a workspace: it always searches the one the request was authorised for. A tier beyond `PLUGIN_SCOPE`, or any but `local` for a workspace API key, raises `PermissionError` |
| `services.llm.embed(text)` | The embedding the core would store for `text` | Chat completion: not offered yet (see below) |
| `services.identity.current()`, `.has_role(role)` | Who is asking, and at what role | Grant anything: it only reads |
| `services.config.get(KEY)` | A declared setting, typed, from `PLUGIN_<PLUGIN>_<KEY>` or its default | Read anything the manifest did not declare |

`PLUGIN_<PLUGIN>_<KEY>` is the plugin's file name upper-cased, with anything but letters and
digits made `_`: `TOP_K` for `my_plugin.py` is `PLUGIN_MY_PLUGIN_TOP_K`.

**Who may use a tool is the core's decision.** A caller below `PLUGIN_MIN_ROLE` is never
offered the plugin's tools, and if the model names one anyway it is refused as an unknown
tool. Roles run viewer < editor < owner (the caller's role in the workspace, or a workspace
API key's) and then admin (a global administrator).

**Not offered yet:** `storage` (tables of the plugin's own) and `llm.complete()`. Each waits
for a plugin that needs it. Tools run synchronously inside the chat stream, so a completion
from inside one needs that changed first. `PLUGIN_CONTRIBUTES` must be `False`.

### Legacy plugins

A file without `setup(services)` loads the way every plugin did before PC-1: it imports
`src.tools.registry` and registers at import time. It still works, is listed with
`"legacy": true` in `GET /api/plugins`, and logs a warning. Its tools are open to every
role. Move it to `setup(services)` — `example_plugin.py` shows the result.

---

## API endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/plugins` | `GET` | List loaded plugins with their tools, manifest, `legacy` flag and any load error — admin only |
| `/api/plugins/reload` | `POST` | Hot-reload all plugins from disk (no restart needed) — admin only |

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `PLUGINS_ENABLED` | `true` | Set to `false` to disable plugin loading |
| `PLUGINS_DIR` | `plugins` | Directory to scan (relative to repo root) |
| `PLUGIN_<PLUGIN>_<KEY>` | the manifest's default | A plugin's declared setting |

---

## Rules

- The contract governs dependencies, not trust. A plugin runs **in the application's
  process** and Python cannot stop it importing `src` or anything else. Treat a plugin as
  code with the application's full authority (SECURITY.md, risk 4). What the contract buys
  is that the core never depends on a plugin, and that a well-behaved plugin cannot reach a
  workspace or a role its caller does not have.
- Tool names must be **unique**. Through `services.tools.register` a taken name is refused.
  A legacy plugin that reuses a name still **replaces** it, with only a warning logged.
- Plugin files starting with `_` (e.g. `__init__.py`) are **skipped**.
- Keep tool handlers **fast**: they run inside the chat stream, and the LLM waits for the result.

---

## Example

See [`example_plugin.py`](example_plugin.py) for a working two-tool example (`word_count`, `reverse_text`) with a manifest and a setting.
