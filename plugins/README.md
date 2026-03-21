# LocalChat Plugin System

Drop a `.py` file here — LocalChat loads it automatically at startup.

---

## How it works

1. On startup, `PluginLoader.load_all()` scans this directory for `*.py` files (skips `_`-prefixed files).
2. Each file is dynamically imported. Any `@tool_registry.register` decorated functions in the file are registered as LLM-callable tools.
3. The LLM can call your tools during chat just like the built-in ones (`search_documents`, `calculate`, etc.).

No source-code changes needed — just drop a file and restart (or call `POST /api/plugins/reload`).

---

## Plugin file contract

```python
# plugins/my_plugin.py

from src.tools.registry import tool_registry

# Optional — shown in GET /api/plugins
PLUGIN_META = {
    "name": "My Plugin",
    "version": "1.0.0",
    "author": "Your Name",
    "description": "What this plugin does.",
}

@tool_registry.register(
    name="my_tool",                          # unique name the LLM uses
    description="What this tool does.",      # shown to the LLM
    parameters={                             # JSON Schema for arguments
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "The input value."},
        },
        "required": ["input"],
    },
)
def my_tool(input: str) -> str:
    return f"You passed: {input}"
```

---

## API endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/plugins` | `GET` | List all loaded plugins and their tools |
| `/api/plugins/reload` | `POST` | Hot-reload all plugins from disk (no restart needed) |

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `PLUGINS_ENABLED` | `true` | Set to `false` to disable plugin loading |
| `PLUGINS_DIR` | `plugins` | Directory to scan (relative to repo root) |

---

## Rules

- Tool names must be **unique** across all plugins and builtins. A plugin that reuses an existing name will overwrite it (a warning is logged).
- Plugin files starting with `_` (e.g. `__init__.py`) are **skipped**.
- Plugins run in the same process — they have full access to the Python environment.
- Keep tool handlers **fast and side-effect-free** where possible; the LLM waits for the result.

---

## Example

See [`example_plugin.py`](example_plugin.py) for a working two-tool example (`word_count`, `reverse_text`).
