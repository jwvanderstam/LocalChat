# Plugin Contract

How plugins extend LocalChat without destabilising the core. Read alongside the
"Plugin Contract" section in `CLAUDE.md` — that states the principle; this is the rule.

> ## ⚠ Status: designed, not built (verified 2026-08-27)
>
> **Everything below describes PC-1..PC-4, which have not been implemented.** They are
> ROADMAP Sprints 10–11, queued behind the PRODUCTION_PLAN exit criteria. None of the
> following exists in the repository today:
>
> | Described here | Reality |
> |---|---|
> | The services catalogue (`retrieval`, `llm`, `storage`, `config`, `identity`) | No service handles; a plugin imports `src.tools.registry` directly |
> | The hooks catalogue (`on_document_ingested`, `on_scheduler_tick`, …) | No hook bus |
> | The manifest (`PLUGIN_SCOPE`, `PLUGIN_MIN_ROLE`, `PLUGIN_HOOKS`, `PLUGIN_CONFIG`) | `plugin_loader.py` reads none of these; it reads an optional `PLUGIN_META` dict for display only |
> | `plugins/_echo/` reference plugin | Absent. `plugins/` holds `example_plugin.py` |
> | The `core-without-plugins` CI job | Absent from `.github/workflows/`, and not in the required-checks ruleset |
>
> **What actually ships** is a much smaller thing, and it is documented accurately in
> [`plugins/README.md`](../../plugins/README.md): drop a `.py` file in `plugins/`, decorate
> functions with `@tool_registry.register`, and they become LLM-callable tools. That is the
> live contract. This file is the target.
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
| `retrieval` | `retrieve(query, scope, workspace_id)` -> ranked chunks. `scope` is `local`/`global`/`hybrid`. | `src/rag/retrieval.py`, pgvector, reranker |
| `llm` | `complete(prompt, ...)`, `embed(text)` | `src/ollama_client.py`, model routing, warm-up |
| `storage` | A namespaced handle for the plugin's own tables; optional Clark-Wilson soft-delete helpers | `src/db/connection.py` pool, psycopg3 |
| `config` | Validated access to the plugin's declared keys + defaults | `src/config.py`, `.env` loading |
| `identity` | `require_role(min_role)` -> ok / 403 | `src/security_fastapi.py`, JWT claims |

**Adding a service.** Only when a real consumer needs it, and only with a name that
describes the capability generically. A `pricing_lookup` service is a leak; a
`retrieval` service that pricing happens to use is correct.

## Hooks catalogue

A plugin subscribes via its manifest. The core calls all subscribers and is unaffected
if there are none.

| Hook | Fires when | Typical use |
|------|-----------|-------------|
| `on_document_ingested` | A document finishes ingest in `SyncWorker._handle_event()` or `processor.py` | Post-process, extract structured data |
| `on_scheduler_tick` | The core scheduler emits a periodic tick | Background evaluation, batch jobs |
| `on_tool_invocation` | An LLM tool call is dispatched (`src/agent/tool_router.py`) | Register LLM-callable tools |
| `on_route_mount` | App startup, router assembly (`src/app_fastapi.py`) | Contribute a FastAPI `APIRouter` |

A subscriber that raises is logged and skipped; the core operation completes normally.
Hooks are best-effort from the core's side.

## The manifest

Every plugin declares a manifest the core reads at load time. Minimal shape:

```python
PLUGIN_SCOPE = "hybrid"        # local | global | hybrid  (retrieval reach)
PLUGIN_MIN_ROLE = "viewer"     # viewer | user | admin     (who may invoke)
PLUGIN_CONTRIBUTES = False     # may it write to the Global Knowledge Base?
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

`.github/workflows/tests.yml` **is to gain** a `core-without-plugins` job (PC-4, not yet
written): it runs the fast suite with `plugins/` emptied (echo excepted, since it lives
in-core as a fixture) and all private plugin paths absent. Red = a plugin dependency
leaked into the core. That job is the architectural IVP and is to be required on every PR
to `main`. **Until it exists, the one rule is enforced by review only.**

## Checklist for a new plugin

- Declares a manifest; owns its config keys; touches no `os.getenv`.
- Requests services by name; imports no `src/` internals directly.
- Creates only its own tables; no core->plugin foreign keys.
- Subscribes to hooks rather than being hard-called by core code.
- Contributes routes via `on_route_mount`, not by editing `app_fastapi.py`.
- The `core-without-plugins` job stays green with the plugin removed.
