# Plugin Contract

How plugins extend LocalChat without destabilising the core. Read alongside the
"Plugin Contract" section in `CLAUDE.md` — that states the principle; this is the rule.

> ## ⚠ Status: partly built (PC-1 built 2026-11-11; PC-2 2026-11-13; PC-4 2026-10-23)
>
> | Described here | Reality |
> |---|---|
> | The manifest (`PLUGIN_SCOPE`, `PLUGIN_MIN_ROLE`, `PLUGIN_HOOKS`, `PLUGIN_CONFIG`) | **Built** (PC-1) in `src/plugins/manifest.py`; a malformed one disables that plugin only |
> | The services catalogue | **Built** (PC-1) in `src/plugins/services.py`: `retrieval`, `llm` (`embed` only), `config`, `identity`, and `tools` for registering. `storage` and `llm.complete` are deferred until a consumer needs them |
> | `PLUGIN_MIN_ROLE` | **Enforced by the core** (PC-1): the tool executor hides and refuses a tool below its minimum role |
> | The hooks catalogue | **Built** (PC-2) in `src/plugins/hooks.py`: `on_document_ingested`, `on_scheduler_tick`, `on_tool_invocation`. `on_route_mount` is deferred until a consumer needs it |
> | `plugins/_echo/` reference plugin | Absent (PC-3). `plugins/` holds `example_plugin.py`, on the PC-1 contract |
> | The `core-without-plugins` CI job | **Built** (2026-10-23) in `.github/workflows/tests.yml`; a required check since 2026-10-30 |
>
> A plugin without `setup(services)` still loads as a *legacy* plugin that imports
> `src.tools.registry` directly. [`plugins/README.md`](../../plugins/README.md) documents
> what ships; the sections below are the target, and say where PC-1 departed from it.
>
> The document is kept in present tense below because it is a specification, and rewriting a
> spec into the conditional makes it harder to build against. Read it as "shall", not "does".
> The one rule at the top — dependencies point inward — **is** binding today: it costs
> nothing to honour before the machinery exists, and it is why the core currently contains
> no reference to any plugin by name.

## The one rule

Dependencies point inward. The core defines extension points; a plugin consumes them.
A plugin never defines a core interface, and the core never references a plugin by name.

If deleting all plugin code leaves the core building, linting, and passing its full
test suite, the rule holds. If it does not, a dependency has leaked.

## Two kinds of extension point

| Kind | Direction | Meaning |
|------|-----------|---------|
| **Service** | plugin -> core | The plugin asks the core for a capability by name. |
| **Hook** | core -> plugin | The core announces an event; subscribed plugins react. |

The core owns the catalogue of both. A plugin uses either; it defines neither.

## Services catalogue

A plugin requests a service handle from the core at load time. It receives an object
with a stable method surface and never imports the core module behind it.

| Service | Surface the plugin gets | Behind it (plugin never touches) |
|---------|------------------------|----------------------------------|
| `retrieval` | `retrieve(query, knowledge_scope, top_k)` -> ranked chunks. `knowledge_scope` is `local`/`global`/`hybrid`, capped by `PLUGIN_SCOPE`; a workspace API key gets `local` only. **No workspace argument:** it searches the workspace the request was authorised for (decided 2026-11-11; the earlier `workspace_id` parameter would have let a plugin choose its target) | `src/rag/retrieval.py`, pgvector, reranker |
| `llm` | `embed(text)`. `complete(prompt, ...)` is deferred: tools run synchronously inside the chat stream, so a completion from one needs that changed first | `src/ollama_client.py`, model routing, warm-up |
| `storage` | *Deferred until a consumer needs it (2026-11-11).* A namespaced handle for the plugin's own tables; optional Clark-Wilson soft-delete helpers. Open: who migrates those tables, and whether RLS applies | `src/db/connection.py` pool, psycopg3 |
| `config` | Validated access to the plugin's declared keys + defaults, from `PLUGIN_<PLUGIN>_<KEY>` | `src/config.py` (`plugin_setting`), `.env` loading |
| `identity` | `current()` -> the caller, `has_role(min_role)` -> bool. Reads only: `PLUGIN_MIN_ROLE` is enforced by the core before a tool runs | `src/utils/caller.py`, bound from the workspace guard |
| `tools` | `register(name, description, parameters)`, tagged with the plugin and its minimum role; a taken name is refused | `src/tools/registry.py` |

**Adding a service.** Only when a real consumer needs it, and only with a name that
describes the capability generically. A `pricing_lookup` service is a leak; a
`retrieval` service that pricing happens to use is correct.

## Hooks catalogue

A plugin subscribes via its manifest: each hook named in `PLUGIN_HOOKS` is a module
function of the same name taking the payload, `def on_document_ingested(payload): ...`. A
hook named without its function is a malformed manifest. The core calls all subscribers
and is unaffected if there are none.

| Hook | Fires when | Payload |
|------|-----------|---------|
| `on_document_ingested` | A document finishes ingest in `DocumentProcessor.ingest_document()`, the one path uploads and connectors share | `document_id`, `filename`, `workspace_id`, `chunks`, `replaced`, `source_id` |
| `on_scheduler_tick` | The core scheduler ticks, every `SCHEDULER_TICK_SECONDS` | `tick` (1, 2, …), `at` (ISO 8601, UTC) |
| `on_tool_invocation` | An LLM tool call the caller was permitted has run (`src/tools/executor.py`) | `tool`, `source` (`builtin` or the plugin) |
| `on_route_mount` | *Deferred (2026-11-13).* Plugins load after the app is assembled, so a router they contribute needs a later mount | — |

A subscriber that raises is logged and skipped; the core operation completes normally.
Hooks are best-effort from the core's side. `emit()` is synchronous and runs subscribers in
the emitting thread, so a slow one slows that operation (an ingest, the scheduler); the tool
loop emits through `asyncio.to_thread`, so a subscriber never stalls the event loop. The
payloads carry identifiers, not content: a tool's arguments hold the user's question, and no
consumer needs them yet.

The weekly reranker fine-tune is the scheduler's first subscriber, a core one: the
scheduler was proven against an existing consumer, not a plugin.

## The manifest

Every plugin declares a manifest the core reads at load time. Minimal shape:

```python
PLUGIN_SCOPE = "hybrid"        # local | global | hybrid  (retrieval reach)
PLUGIN_MIN_ROLE = "viewer"     # viewer | editor | owner | admin  (who may invoke)
PLUGIN_CONTRIBUTES = False     # may it write to the GKB? Must be False: no service writes
PLUGIN_HOOKS = ["on_document_ingested", "on_scheduler_tick", "on_tool_invocation"]
PLUGIN_CONFIG = {              # keys the core loads into the config service
    "FEEDBACK_THRESHOLD": ("float", 0.30),
}
```

The core validates the manifest, loads the config keys, wires the hooks, and exposes
the requested services. A malformed or failing manifest disables that plugin and logs;
the application starts normally.

## Capabilities on demand

This catalogue lists only what current consumers (the reference echo plugin and the
pricing plugin) require. Do not pre-build speculative services or hooks. When a new
consumer needs a capability that is not here, add it under the one rule and the
generic-name test, update this file in the same commit, and add its row above.

## The reference plugin

The core **will ship** a trivial `plugins/_echo/` reference plugin that exercises every
service and hook with no domain logic (PC-3; it does not exist yet). It is the core's own fixture: each capability is proven
generically against echo, never against a domain plugin. A domain plugin (pricing) is
always the *second* consumer of any capability — never the first, never the author.

## Enforcement

`.github/workflows/tests.yml` has a `core-without-plugins` job (PC-4, built 2026-10-23):
it deletes everything in `plugins/` except its README, then runs `ruff` and the fast suite.
Once PC-3 ships, the echo fixture is kept too, since it lives in-core. Red = a plugin
dependency leaked into the core. That job is the architectural IVP. It has been a required
check on every PR to `main` since 2026-10-30.

## Checklist for a new plugin

- Declares a manifest; owns its config keys; touches no `os.getenv`.
- Requests services by name; imports no `src/` internals directly.
- Creates only its own tables; no core->plugin foreign keys.
- Subscribes to hooks rather than being hard-called by core code.
- Contributes routes via `on_route_mount`, not by editing `app_fastapi.py`.
- The `core-without-plugins` job stays green with the plugin removed.
