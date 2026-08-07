# Route Permission Matrix

**Generated from the route table on 2026-08-05 (RBAC-2).** Every row is the guard actually
present in the handler, read from source — not an intention. Regenerate after changing any
route; drift between this file and the code is the failure mode it exists to prevent.

> **Known limitation of the generator.** It detects guards declared in the handler —
> `require_admin_dep`, `require_auth`, and `check_workspace_access` via `_authz.deny()`. It does
> **not** see authorisation performed inside a called helper. One route pair does exactly that:
> `/metrics` and `/metrics.json` enforce `METRICS_TOKEN` through `_check_metrics_auth()` and were
> initially listed here as plain `public`. Corrected below. Treat `public` as "no *declared*
> guard", and check the handler body before concluding a route is open.

## The levels

| Level | Meaning | Mechanism |
|---|---|---|
| `public` | No credentials required. Every entry is deliberate — see the allowlist below. | none |
| `authenticated` | Any logged-in user. Used where no workspace context exists yet. | `require_auth` |
| `ws:viewer` / `ws:editor` / `ws:owner` | Membership of the active workspace, at that level or higher. | `check_workspace_access` via `_authz.deny()` |
| **`admin`** | Global `users.role = 'admin'`. Node-wide operations. | `require_admin_dep` |

**Two kinds of principal reach the `ws:*` levels.** A *user*, whose role comes from
`workspace_members`; and a *workspace API key*, which carries its own role and is pinned to
one workspace (see [WORKSPACE_API_KEYS.md](WORKSPACE_API_KEYS.md)). A key never receives the
global-admin short-circuit and can never reach a second workspace, so every `admin` row below
is closed to keys by construction.

Global `admin` short-circuits every workspace check, so an admin passes all `ws:*` rows.

## Distribution

| Level | Routes |
|---|---|
| **admin** | 27 |
| ws:viewer | 19 |
| public | 18 |
| ws:owner | 14 |
| ws:editor | 13 |
| authenticated | 11 |
| **Total** | **102** |

Before RBAC-2, **49 of these 102 had no check at all** — including `POST /api/models/pull`,
`DELETE /api/models/delete` and `POST /api/plugins/reload`, none of which did an internal
check either.

## The public allowlist

These 18 are unauthenticated **by decision**, each for a stated reason:

| Routes | Why public |
|---|---|
| `web`: `/`, `/chat`, `/documents`, `/models`, `/settings`, `/docs`, `/favicon.ico` | SPA shells. They carry no data; every API call they make is itself guarded. |
| `settings`: `/health` | The container healthcheck calls it with no credentials. |
| `settings`: `/metrics`, `/metrics.json` | **Conditionally public.** Both call `_check_metrics_auth()` (`settings_routes.py:158,170`) and return 403 unless a `Bearer` token matching `METRICS_TOKEN` is supplied. With `METRICS_TOKEN` empty — the default — they are open, so Prometheus can scrape without a header. Set it to close them. |
| `docs`: `/`, `/{slug}`, `/{slug}/fragments/{...}` | Serves the same markdown that is public in the repository. |
| `oauth`: `microsoft/callback`, `google/callback` | The identity provider redirects here and carries no bearer token. `authorize`, `status` and `disconnect` **do** require authentication. |
| `connector`: `/connectors/{id}/webhook` | External systems POST here. Authenticity is the webhook's own concern, not the session's. |
| `auth`: `/auth/login` | The route that establishes a session cannot require one. Rate-limited (`RATELIMIT_LOGIN`, 10/min) and returns one message for both unknown-user and wrong-password, so it is not a username oracle. |
| `web`: `/login` | The login page must render without a session, or the 401 redirect loops. |
| `auth`: `/logout`, `/users/me/password` | Self-service; both resolve and verify the caller internally. |

## Full table

| Module | Method | Path | Minimum role |
|---|---|---|---|
| `annotation` | POST | `/annotations` | ws:editor |
| `annotation` | GET | `/chunks/{chunk_id}/annotations` | ws:viewer |
| `annotation` | DELETE | `/annotations/{annotation_id}` | ws:editor |
| `api` | GET | `/status` | authenticated |
| `api` | POST | `/chat` | ws:viewer |
| `api` | GET | `/plugins` | **admin** |
| `api` | POST | `/plugins/reload` | **admin** |
| `auth` | POST | `/users` | **admin** |
| `auth` | GET | `/users` | **admin** |
| `auth` | GET | `/users/me` | ws:viewer |
| `auth` | GET | `/users/{user_id}` | **admin** |
| `auth` | PUT | `/users/{user_id}` | **admin** |
| `auth` | DELETE | `/users/{user_id}/purge` | **admin** |
| `auth` | DELETE | `/users/{user_id}` | **admin** |
| `auth` | POST | `/users/me/password` | public |
| `auth` | POST | `/logout` | public |
| `connector` | GET | `/connectors/available` | ws:owner |
| `connector` | GET | `/connectors/types` | ws:owner |
| `connector` | GET | `/connectors` | ws:owner |
| `connector` | POST | `/connectors` | ws:owner |
| `connector` | GET | `/connectors/{connector_id}` | ws:owner |
| `connector` | PUT | `/connectors/{connector_id}` | ws:owner |
| `connector` | DELETE | `/connectors/{connector_id}/purge` | **admin** |
| `connector` | DELETE | `/connectors/{connector_id}` | ws:owner |
| `connector` | POST | `/connectors/{connector_id}/sync` | ws:owner |
| `connector` | GET | `/connectors/{connector_id}/history` | ws:owner |
| `connector` | POST | `/connectors/{connector_id}/webhook` | public |
| `docs` | GET | `/` | public |
| `docs` | GET | `/{slug}` | public |
| `docs` | GET | `/{slug}/fragments/{fragment_slug}` | public |
| `document` | POST | `/upload` | ws:editor |
| `document` | GET | `/list` | ws:viewer |
| `document` | GET | `/stats` | ws:viewer |
| `document` | POST | `/test` | ws:viewer |
| `document` | POST | `/search-text` | ws:viewer |
| `document` | GET | `/chunks/{chunk_id}/context` | ws:viewer |
| `document` | DELETE | `/clear` | ws:editor |
| `document` | DELETE | `/{doc_id}/purge` | **admin** |
| `document` | DELETE | `/{doc_id}` | ws:editor |
| `feedback` | POST | `/feedback` | ws:viewer |
| `feedback` | GET | `/feedback/stats` | **admin** |
| `longterm_memory` | GET | `/` | ws:viewer |
| `longterm_memory` | POST | `/extract` | ws:editor |
| `longterm_memory` | DELETE | `/{memory_id}` | ws:editor |
| `longterm_memory` | DELETE | `/` | ws:editor |
| `memory` | GET | `/conversations` | ws:viewer |
| `memory` | POST | `/conversations` | ws:editor |
| `memory` | DELETE | `/conversations` | ws:editor |
| `memory` | GET | `/conversations/{conversation_id}` | ws:viewer |
| `memory` | GET | `/conversations/{conversation_id}/export` | ws:viewer |
| `memory` | GET | `/conversations/{conversation_id}/documents` | ws:viewer |
| `memory` | PUT | `/conversations/{conversation_id}/documents` | ws:editor |
| `memory` | PATCH | `/conversations/{conversation_id}` | ws:editor |
| `memory` | DELETE | `/conversations/{conversation_id}/purge` | **admin** |
| `memory` | DELETE | `/conversations/{conversation_id}` | ws:editor |
| `model` | GET | `/` | **admin** |
| `model` | GET | `/active` | **admin** |
| `model` | POST | `/active` | **admin** |
| `model` | POST | `/pull` | **admin** |
| `model` | DELETE | `/delete` | **admin** |
| `model` | POST | `/unload` | **admin** |
| `model` | POST | `/test` | **admin** |
| `oauth` | GET | `/oauth/microsoft/authorize` | authenticated |
| `oauth` | GET | `/oauth/microsoft/callback` | public |
| `oauth` | GET | `/oauth/microsoft/status` | authenticated |
| `oauth` | DELETE | `/oauth/microsoft/disconnect` | authenticated |
| `oauth` | GET | `/oauth/google/authorize` | authenticated |
| `oauth` | GET | `/oauth/google/callback` | public |
| `oauth` | GET | `/oauth/google/status` | authenticated |
| `oauth` | DELETE | `/oauth/google/disconnect` | authenticated |
| `settings` | GET | `/health` | public |
| `settings` | GET | `/metrics` | public |
| `settings` | GET | `/metrics.json` | public |
| `settings` | GET | `/settings/stats` | **admin** |
| `settings` | GET | `/settings/rag` | **admin** |
| `settings` | POST | `/settings/rag` | **admin** |
| `settings` | GET | `/reranker/status` | **admin** |
| `settings` | POST | `/reranker/train` | **admin** |
| `settings` | POST | `/reranker/promote/{version_id}` | **admin** |
| `settings` | POST | `/reranker/rollback/{version_id}` | **admin** |
| `web` | GET | `/favicon.ico` | public |
| `web` | GET | `/` | public |
| `web` | GET | `/chat` | public |
| `web` | GET | `/documents` | public |
| `web` | GET | `/models` | public |
| `web` | GET | `/settings` | public |
| `web` | GET | `/docs` | public |
| `workspace` | GET | `/workspaces` | authenticated |
| `workspace` | POST | `/workspaces` | authenticated |
| `workspace` | GET | `/workspaces/active` | authenticated |
| `workspace` | POST | `/workspaces/switch` | authenticated |
| `workspace` | GET | `/workspaces/{workspace_id}` | ws:viewer |
| `workspace` | PUT | `/workspaces/{workspace_id}` | ws:owner |
| `workspace` | DELETE | `/workspaces/{workspace_id}/purge` | **admin** |
| `workspace` | DELETE | `/workspaces/{workspace_id}` | ws:owner |
| `workspace` | GET | `/workspaces/{workspace_id}/members` | ws:viewer |
| `workspace` | POST | `/workspaces/{workspace_id}/members` | ws:owner |
| `workspace` | PUT | `/workspaces/{workspace_id}/members/{user_id}` | ws:owner |
| `workspace` | DELETE | `/workspaces/{workspace_id}/members/{user_id}` | ws:owner |
| `workspace` | GET | `/workspaces/{workspace_id}/presence` | ws:viewer |
| `workspace` | GET | `/workspaces/{workspace_id}/suggestions` | ws:viewer |
| `workspace` | GET | `/workspaces/{workspace_id}/ontology` | ws:viewer |