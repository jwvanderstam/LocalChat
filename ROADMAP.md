# ROADMAP — v3.0

> **Status:** Planning  
> **Predecessor:** v2.0 completed May 2026 (dual-stack migration, JWT revocation, Alembic migrations, CI integration tests, chat.js ES modules).

v3.0 targets three architectural principles: **data integrity hardening** (Clark-Wilson compliance), **role-based access control** (admin / user / viewer), and **two-tier knowledge architecture** (Global Knowledge Base + workspace-scoped projects).

---

## Initiative 1 — Clark-Wilson Compliance

The Clark-Wilson integrity model requires that no delete operation leaves referentially-linked data in an inconsistent state. The current codebase has ~12 hard-delete operations across CDI tables. All of them will be converted to soft-delete state transitions.

**CDIs in scope:** `documents`, `document_chunks`, `conversations`, `messages`, `users`, `workspaces`, `memories`, `annotations`, `connectors`

---

### CW-1 — Document soft-delete (pilot ticket)

**Why first:** Documents are the highest-integrity CDI. Chunk IDs are embedded in citation references inside conversation history. A hard-deleted document currently produces ghost citations — the conversation record references a chunk that no longer exists, and no IVP can repair it.

**Schema changes (Alembic migration):**
```sql
ALTER TABLE documents        ADD COLUMN deleted_at  TIMESTAMPTZ;
ALTER TABLE documents        ADD COLUMN deleted_by  UUID REFERENCES users(id);
ALTER TABLE document_chunks  ADD COLUMN deleted_at  TIMESTAMPTZ;
```

**Behaviour changes:**
- `DELETE /api/documents/{id}` → sets `deleted_at`, `deleted_by`; does not touch chunks immediately
- All document SELECT queries → add `WHERE deleted_at IS NULL`
- Chunk retrieval in RAG → add `WHERE deleted_at IS NULL` to similarity search
- Citations → resolve against all chunks (including soft-deleted) so existing conversation history remains valid; UI can surface a "source retired" indicator
- New admin endpoint `DELETE /api/documents/{id}/purge` → hard-deletes only if no conversation cites any chunk from this document; returns 409 otherwise
- File on disk → moved to a `uploads/retired/` sub-directory on soft-delete; physically removed only on purge

**Tests required:**
- Unit: `delete_document` sets `deleted_at`, does not remove rows
- Unit: `purge_document` raises precondition error when citations exist, succeeds when none
- Integration: upload → chat (creates citation) → soft-delete → confirm RAG excludes it → confirm citation still resolves → purge blocked by citation
- Integration: upload → soft-delete → purge succeeds when no citations

**Files:** `src/db/documents.py`, `src/routes_fastapi/document_routes.py`, `src/rag/retrieval.py`, Alembic migration

---

### CW-2 — Full CDI soft-delete sweep

Apply the same pattern to all remaining CDIs. Each sub-item is one migration + one mixin change + route update.

| Sub-ticket | Table(s) | Hard-delete locations today |
|---|---|---|
| CW-2a | `conversations`, `messages` | `db/conversations.py` — `delete_conversation`, `clear_conversations` |
| CW-2b | `users` | `db/users.py` — `delete_user` |
| CW-2c | `workspaces` | `db/workspaces.py` — `delete_workspace` |
| CW-2d | `memories` | `db/memories.py` — `delete_memory`, `clear_memories` |
| CW-2e | `annotations` | `db/annotations.py` — `delete_annotation` |
| CW-2f | `connectors` | `db/connectors.py` — `delete_connector`, `delete_document_by_filename` |

**Shared pattern for each sub-ticket:**
1. Alembic migration: add `deleted_at TIMESTAMPTZ`, `deleted_by UUID` columns
2. Mixin: replace `DELETE FROM` with `UPDATE ... SET deleted_at = NOW(), deleted_by = %s`
3. All SELECT queries in that mixin: add `WHERE deleted_at IS NULL`
4. Route: delete endpoint soft-deletes; purge endpoint (admin-only) hard-deletes with precondition
5. Unit tests for both operations

**Cross-cutting concern — purge preconditions:**

| CDI | Purge blocked when... |
|---|---|
| conversation | conversation is shared across workspaces or cited in a memory |
| user | user owns documents, workspaces, or has active conversations |
| workspace | workspace contains documents or conversations |
| memory | memory is referenced in a conversation context |
| annotation | annotation is included in an export |
| connector | connector has synced documents that are active |

---

### CW-3 — Audit log

Once soft-delete is in place everywhere, a single `audit_log` table can record all CDI state transitions (create, update, retire, purge) with actor, timestamp, and before/after state snapshot. This is the IVP layer — a query over `audit_log` can reconstruct the integrity state at any point in time.

**This ticket is a stretch goal for v3.0 and may slip to v4.0.**

---

## Initiative 2 — Role-Based Access Control

The current system has two application-level roles: `admin` and `user`. A `viewer` role is needed for read-only access — consumers of the knowledge base who should not be able to modify it.

---

### RBAC-1 — Viewer role definition and enforcement

**Proposed role matrix** *(scope to be confirmed before implementation)*

| Capability | admin | user | viewer |
|---|---|---|---|
| Chat / query the knowledge base | ✓ | ✓ | ✓ |
| View document list | ✓ | ✓ | ✓ |
| View own conversation history | ✓ | ✓ | ✓ |
| Upload documents | ✓ | ✓ | — |
| Delete (soft) own documents | ✓ | ✓ | — |
| Manage own conversations | ✓ | ✓ | — |
| Change own password | ✓ | ✓ | — |
| Create / manage workspaces | ✓ | ✓ | — |
| View system settings | ✓ | — | — |
| Change RAG parameters | ✓ | — | — |
| User management | ✓ | — | — |
| Purge (hard-delete) any CDI | ✓ | — | — |
| Trigger reranker training | ✓ | — | — |

**Key design decisions to confirm:**
- Can a viewer see *all* documents in a workspace, or only documents uploaded by others that are explicitly shared?
- Can a viewer export conversations they participated in?
- Is the viewer role workspace-scoped (a user can be a viewer in workspace A and a user in workspace B) or global?

**Implementation:**
- Add `"viewer"` as valid role value in `src/db/users.py` `create_user` and `update_user`
- Add `require_role_dep(min_role: Literal["viewer", "user", "admin"])` to `src/security_fastapi.py`
- Audit every route handler and replace `require_admin_dep` / open access with the appropriate `require_role_dep` call
- Update `POST /api/users` validation: accept `"viewer"` in addition to `"admin"` and `"user"`
- Update JWT claims: `role` claim carries the user's global role
- UI: hide upload, delete, and settings controls for viewer-role sessions

**Files:** `src/security_fastapi.py`, `src/db/users.py`, `src/routes_fastapi/auth_routes.py`, all route modules, `static/js/`

**Tests required:**
- Unit: `require_role_dep("user")` rejects viewer token
- Unit: `require_role_dep("viewer")` accepts viewer, user, and admin tokens
- Integration: viewer can call `GET /api/chat` but receives 403 on `POST /api/documents/upload`
- Integration: admin can promote a user to viewer and back

---

### RBAC-2 — Route permission audit

A systematic pass over every route to assign the correct minimum role. This is separate from RBAC-1 (which adds the mechanism) — this ticket applies it consistently and documents the result in a permission matrix in `docs/`.

---

## Sprint Plan

| Sprint | Tickets | Est. duration |
|---|---|---|
| 1 | CW-1 (document soft-delete pilot) | 1 week |
| 2 | CW-2a + CW-2b (conversations, users) | 1 week |
| 3 | CW-2c + CW-2d + CW-2e + CW-2f (workspaces, memories, annotations, connectors) | 1 week |
| 4 | RBAC-1 (viewer role) — pending scope confirmation | 1 week |
| 5 | RBAC-2 (route permission audit) + CW-3 (audit log, stretch) | 1 week |
| 6 | GKB-1 (schema + two-tier retrieval) | 1 week |
| 7 | GKB-2 (contribution workflow) | 1 week |
| 8 | GKB-3 (pricing plugin — reference implementation) | 1–2 weeks |
| **Total** | | **~8–9 weeks** |

---

## Initiative 3 — Global Knowledge Base (GKB)

### Background

Workspaces are project containers — isolated knowledge silos scoped to a team and a deliverable. But certain plugins (pricing, competitive intelligence, risk scoring) need to learn from patterns that emerge *across* all projects, not just within one. A single-tier workspace model cannot serve both needs.

**The two-tier pattern:**

```
┌─────────────────────────────────────────────────┐
│           GLOBAL KNOWLEDGE BASE (GKB)           │
│  Narrative knowledge contributed from projects.  │
│  No workspace_id. Readable by all plugins.       │
└────────────────┬────────────────────────────────┘
                 │ contributes on close ↑
                 │ global context on query ↓
    ┌────────────┴──────┐   ┌───────────────────┐
    │   Project A        │   │   Project B        │
    │   (Workspace)      │   │   (Workspace)      │
    └───────────────────┘   └───────────────────┘
```

- **GKB** — `document_chunks` rows with `workspace_id = NULL`. Same pgvector infrastructure; no schema invention.
- **Contribution** — a deliberate human act by the workspace owner. Not automatic. Not a pipeline.
- **Knowledge form** — fuzzy narrative (retrospectives, lessons learned), not structured facts. Vector retrieval handles fuzziness natively.
- **Plugin scope** — plugins declare `local`, `global`, or `hybrid`. The pricing plugin is `hybrid`: retrieves from GKB for patterns, from the active workspace for project specifics, and hands the merged context to the LLM.

---

### GKB-1 — Schema and two-tier retrieval

**Schema changes (Alembic migration):**
- `document_chunks.workspace_id` is already nullable in practice — confirm the column allows NULL; add index on `workspace_id IS NULL` for global-tier queries.
- Add `contributed_at TIMESTAMPTZ`, `contributed_by UUID`, `archived_at TIMESTAMPTZ` to `document_chunks` for GKB-tier rows. This supports staleness management without polluting project chunks.
- Add `source_project_id UUID` (references `workspaces.id`, nullable) — provenance for contributed chunks.
- Add `outcome VARCHAR(32)` and `sector VARCHAR(128)` metadata columns on contributed chunks (structured envelope around fuzzy content).

**Retrieval changes (`src/rag/retrieval.py`):**
- Add `scope: Literal["local", "global", "hybrid"] = "local"` parameter to `retrieve_context()`.
- `local` — existing behaviour, `WHERE workspace_id = %s`.
- `global` — `WHERE workspace_id IS NULL AND archived_at IS NULL`.
- `hybrid` — run both queries, merge results, deduplicate, re-rank. The existing reranker handles merged result sets naturally.

**Tests:** unit tests for each scope mode; integration test confirming hybrid merge returns results from both tiers.

---

### GKB-2 — Contribution workflow

A workspace owner (or admin) marks a project as contributing to the GKB. They select which documents cross the project boundary and approve a contribution narrative before ingestion.

**Backend:**
- `POST /api/workspaces/{id}/contribute` — accepts a list of `document_ids` and an optional `narrative` (free text). Ingests selected documents into the GKB tier (`workspace_id = NULL`) with contribution metadata. The narrative, if provided, is ingested as an additional chunk.
- `DELETE /api/workspaces/{id}/contributions` — archives all GKB chunks contributed from this workspace (`SET archived_at = NOW()`). Does not hard-delete (Clark-Wilson).
- `GET /api/gkb/chunks` — admin endpoint; lists all GKB chunks with provenance and metadata.

**UI:**
- "Contribute to Global Knowledge" action on the workspace settings page (owner-only).
- Document selector with optional narrative text area.
- Review screen showing what will be contributed before confirmation.

**Guardrails:**
- Contribution requires workspace `owner` role (not `editor` or `viewer`).
- Admin can revoke a contribution (archive) without deleting the workspace.
- Contributed documents are tagged in the workspace document list as "shared globally."

---

### GKB-3 — Pricing plugin (reference implementation)

The pricing plugin is the first `hybrid`-scope plugin. It serves as the reference implementation for all future cross-workspace plugins.

**Scope:** price-to-win analysis for an active project.

**Query flow:**
1. User asks: "What should we price this project at?"
2. Plugin extracts context signals from the question and active workspace (project type, scope, client sector, timeline).
3. GKB retrieval: semantic search over global chunks filtered by `outcome`, `sector` metadata where available.
4. Project retrieval: semantic search over active workspace chunks (RFP, requirements, client notes).
5. Merged context → LLM → price-to-win narrative with reasoning.

**Plugin manifest (declares scope):**
```python
PLUGIN_SCOPE = "hybrid"          # reads GKB + active workspace
PLUGIN_CONTRIBUTES = False       # does not write to GKB (contribution is manual)
PLUGIN_MIN_ROLE = "viewer"       # any workspace member can query
```

**Implementation files:** `plugins/pricing/` (new), `src/tools/registry.py` (scope-aware dispatch), `src/rag/retrieval.py` (GKB-1 already covers the retrieval layer).

**Tests:** integration test with seeded GKB chunks + project workspace chunks; assert hybrid query returns from both; assert global-only query excludes project chunks.

---

## What This Does Not Cover

| Item | Decision |
|---|---|
| Multi-tenancy / SaaS isolation | Out of scope — LocalChat is self-hosted |
| OAuth / SSO for viewer-only access | Defer to v4.0 |
| Row-level security in PostgreSQL | Defer — application-level RBAC sufficient for self-hosted deployment |
| Purge scheduler (auto-purge after N days) | Defer — manual purge is sufficient; scheduled purge is a separate feature |
| Automatic signal extraction pipeline | Defer — human-curated retrospectives are the contribution model; ML extraction is v4.0 |
| GKB staleness / decay scoring | Defer — `archived_at` column reserved; active staleness weighting is a future retrieval improvement |
