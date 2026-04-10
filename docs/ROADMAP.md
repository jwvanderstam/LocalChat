# LocalChat Roadmap
## Path to the Greatest Local RAG Application

> Last updated: 2026-04-10
> Current version: v1.0.1
> **Status: All four phases complete — agentic RAG with MCP composability delivered**

---

## Table of Contents

1. [Vision](#vision)
2. [Current State](#current-state)
3. [Gap Analysis](#gap-analysis)
4. [Phase 1 — Foundation (M1–M2)](#phase-1--foundation-m1m2)
5. [Phase 2 — Intelligence (M3–M5)](#phase-2--intelligence-m3m5)
6. [Phase 3 — Architecture (M6–M9)](#phase-3--architecture-m6m9)
7. [Phase 4 — Platform (M10–M12)](#phase-4--platform-m10m12)
8. [Target Architecture](#target-architecture)
9. [Effort vs. Impact Matrix](#effort-vs-impact-matrix)
10. [Design Principles](#design-principles)
11. [Dependencies & Stack Decisions](#dependencies--stack-decisions)

---

## Vision

LocalChat exists to be the gold standard for local, privacy-preserving knowledge management. The target state is an **agentic RAG system** with:

- An explicit **Aggregator Agent** that plans, reasons, and orchestrates specialist sub-agents
- A **knowledge layer** that learns from each interaction and improves its own retrieval quality
- **MCP-based composability** so every data domain — local files, web, cloud — is independently deployable
- A **transparent UX** where every answer shows its sources and every plan can be inspected

Unlike cloud RAG tools, LocalChat's advantage compounds over time: domain-adapted retrieval, workspace-scoped memory, and a feedback loop that builds a moat no generic product can replicate.

---

## Current State

LocalChat today is a well-structured Flask monolith with a solid retrieval foundation:

| Component | Status |
|---|---|
| RAG pipeline | ✅ Chunking, retrieval, reranking, Ollama calls |
| Vector store | ✅ PostgreSQL + pgvector (HNSW indexing) |
| Hybrid search | ✅ Semantic + BM25 |
| Web search | ✅ DuckDuckGo (in-process module) |
| Plugin system | ✅ Exists, but co-located (not routable agents) |
| MCP server | ✅ Directory exists, not yet primary interface |
| Admin dashboard | ✅ Prometheus metrics, GPU monitoring, cache stats |
| Security | ✅ JWT, rate limiting, XSS mitigations |
| Model layer | ⚠️ Single active Ollama model, no router |
| Agent layer | ❌ No explicit planner or aggregator |
| Memory | ❌ Conversation history only, no long-term store |
| Source attribution | ❌ Chunks retrieved but not surfaced in UI |
| Feedback loop | ❌ No user signal collection |
| Multi-model | ❌ No routing between model families |

---

## Gap Analysis

Five structural gaps separate LocalChat from the agentic RAG vision:

### 1. Agentic Orchestration
The RAG pipeline executes as a monolithic sequence. There is no explicit planner that decomposes queries, no aggregator that routes to specialist agents, and no observable reasoning trace. All tool calls (web search, docs, plugins) happen in the same process via Python imports rather than as independently addressable agents.

### 2. Memory & Planning
Conversation history is persisted in Postgres, but there is no long-term memory layer that distills history into reusable facts. There is also no explicit query planner — planning is implicit in prompt construction and retrieval logic.

### 3. Retrieval Ceiling
The hybrid retrieval (semantic + BM25) is good for passage-level similarity but cannot answer multi-hop questions that require reasoning over entity relationships. There is also no per-document-type chunking strategy — all documents go through the same pipeline regardless of structure.

### 4. Model Layer
A single Ollama model handles all query types. There is no routing logic to direct simple lookups to a fast/cheap model, complex synthesis to a larger model, or image-heavy documents to a vision model.

### 5. UX Trust & Feedback
Answers do not show their sources in the UI, making it impossible for users to verify claims. There is no mechanism for users to signal whether an answer was good, and no pipeline for those signals to improve retrieval quality.

---

## Phase 1 — Foundation (M1–M2)

**Theme:** Ship the highest-trust, lowest-effort improvements immediately. Establish the feedback infrastructure and fix the most visible UX gaps before touching architecture.

### Feature 1.1 — Answer Attribution + Source Viewer

**Effort:** Low | **Impact:** High

**What:** Every generated answer shows inline citations — document name, chunk ID, page or section. Users can click through to the exact source passage highlighted in context.

**Why:** The single biggest trust signal for knowledge-worker users. Without it, LocalChat is a black box. Enterprise users will not adopt a system whose answers they cannot verify. This is a UI feature, not a model feature — it is fast to ship and immediately changes the user relationship with the system.

**How:**
1. The RAG pipeline already returns chunk metadata alongside generated text. Expose `chunk_id`, `document_name`, `page_number`, and `section` in the API response alongside the answer.
2. Add a citation rendering component to the chat frontend. Each cited sentence gets a superscript reference (`[1]`, `[2]`) that opens a side panel.
3. Build a document viewer panel that loads the source document and highlights the relevant passage. Use the existing chunk boundary coordinates for highlight positioning.
4. Add a `GET /api/chunks/{chunk_id}/context` endpoint that returns the chunk plus N surrounding chunks for reading context.

**Acceptance criteria:**
- Every RAG answer includes at least one citation
- Clicking a citation opens the source document at the correct passage
- Citation panel shows: document name, page/section, date ingested

---

### Feature 1.2 — Adaptive Chunking per Document Type

**Effort:** Low | **Impact:** High

**What:** Detect document type on ingest and apply a type-specific chunking strategy rather than applying one universal chunker to all content.

**Why:** A slide deck, a legal contract, a Python file, and an email thread have completely different structural semantics. Applying sentence-boundary chunking to a slide deck destroys slide-level context. Applying it to code destroys function-level context. Type-aware chunking directly improves retrieval precision with no model changes and no infrastructure work.

**How:**

| Document type | Detection | Chunking strategy |
|---|---|---|
| Slide deck (.pptx, .ppt) | Extension | One chunk per slide (title + body) |
| Source code (.py, .js, .ts, .java…) | Extension + content | One chunk per function/class (AST-based) |
| Email thread (.eml, .msg) | MIME type | One chunk per message |
| Legal/contract document | Keyword heuristics | One chunk per numbered clause |
| Markdown / plain prose | Default | Sentence-boundary with overlap |
| Spreadsheet (.xlsx, .csv) | Extension | One chunk per logical table with header context |

Implementation:
1. Add a `DocTypeClassifier` that maps file extension + content heuristics to a document type enum.
2. Add a `ChunkerRegistry` that maps document types to chunker implementations.
3. Store `doc_type` and `chunker_version` on the `documents` table to support re-chunking on strategy upgrades.
4. Expose a bulk re-chunk endpoint for existing documents.

**Acceptance criteria:**
- Python files are chunked at function boundaries
- PPTX files produce one chunk per slide
- Email threads produce one chunk per message
- All existing document types continue to work via the default chunker

---

### Feature 1.3 — Cloud Model Fallback (Local-First Policy)

**Effort:** Low | **Impact:** Medium

**What:** Add optional API key configuration for OpenAI, Anthropic, and Gemini. When the local model fails a confidence check or the query is flagged as requiring stronger reasoning, fall back to a cloud model — with a clear UI indicator and user consent.

**Why:** Some queries genuinely exceed what a local model can handle well, especially complex multi-document synthesis or queries requiring broad world knowledge. A cloud fallback gives users a practical escape hatch without abandoning the local-first ethos. Sensitive documents remain local; hard reasoning gets cloud horsepower. This is configurable and off by default.

**How:**
1. Add a `LiteLLM` adapter layer. All Ollama calls go through a unified `ModelClient` interface.
2. Add cloud provider configs to `settings.py`: `CLOUD_PROVIDER`, `CLOUD_API_KEY`, `CLOUD_MODEL`.
3. After local generation, compute a confidence proxy (e.g. response perplexity, refusal detection, or answer length heuristic for "I don't know" patterns). If below threshold, retry with cloud model.
4. Add a privacy flag on documents: `local_only: bool`. Documents marked `local_only` never send chunks to cloud providers, even in fallback mode.
5. Show a `⚡ cloud` badge in the chat UI when a cloud model was used.

**Acceptance criteria:**
- Cloud fallback is disabled by default
- `local_only` documents never reach cloud APIs regardless of settings
- UI clearly distinguishes local vs cloud responses
- Fallback adds < 500ms of latency overhead (confidence check is synchronous)

---

## Phase 2 — Intelligence (M3–M5)

**Theme:** Make LocalChat smarter about how it reasons and what it remembers. Add the planning and memory layers that let the system handle complex, multi-session knowledge work.

### Feature 2.1 — Query Planner + Chain-of-Thought Trace UI

**Effort:** Medium | **Impact:** High

**What:** Add an explicit planning step before retrieval. Given a user query, the planner emits a structured plan: sub-questions to answer, tools to invoke, order of operations, and whether the query requires synthesis across multiple sources. Surface this plan as a collapsible "reasoning" panel in the chat UI.

**Why:** Without a planner, multi-hop questions fail silently — the retriever fetches passages that are individually relevant but collectively insufficient. With a planner, the system decomposes "Compare the security postures of system A and system B with respect to our compliance requirements" into three retrievals and a synthesis step. Users who can see the plan can also correct it, turning a black box into a collaborative reasoning partner.

**How:**

```
User query
    │
    ▼
┌─────────────────────┐
│    Query Planner    │  ← lightweight LLM call with structured output
└─────────────────────┘
    │  Emits: Plan JSON
    ▼
{
  "intent": "comparison",
  "sub_questions": ["What is A's auth model?", "What is B's auth model?"],
  "tools": ["local_docs", "local_docs"],
  "synthesis_required": true,
  "estimated_hops": 2
}
    │
    ▼
Parallel retrieval per sub-question
    │
    ▼
Synthesis prompt with all retrieved contexts
    │
    ▼
Answer + cited sources
```

Implementation:
1. Add `rag/planner.py`. Use a structured output prompt (JSON mode) against the active model. The planner prompt is short and fast — it does not retrieve, only classifies and decomposes.
2. Store `plan_json` alongside each conversation turn in `conversation_history`.
3. Add a `PlanTrace` component to the frontend. Collapsed by default, expandable with a chevron. Shows intent, sub-questions, tools used, and hop count.
4. Use the plan's `tools` array to dispatch parallel retrieval calls. Merge results before synthesis.
5. Add a `plan_feedback` signal: thumbs up/down on the plan itself (separate from answer quality).

**Acceptance criteria:**
- All queries go through the planner (< 200ms overhead on fast models)
- Multi-hop queries produce measurably better answers (eval on held-out test set)
- Plan trace is visible and collapsible in UI
- Single-hop simple queries produce minimal plans without overhead

---

### Feature 2.2 — Long-Term Memory Store

**Effort:** Medium | **Impact:** High

**What:** Distill conversation history into a persistent, structured memory layer. Rather than only retrieving document chunks, the system also retrieves relevant memories — user preferences, domain facts, past decisions, recurring entities — and incorporates them into each response.

**Why:** The single biggest UX gap between LocalChat and commercial tools like Perplexity or Copilot. Users feel heard when the system remembers that they prefer concise answers, that "NMBS" refers to a specific client, or that a decision was made two weeks ago. Memory is what makes a RAG system feel like a knowledge partner rather than a search engine.

**How:**

**Data model:**
```sql
CREATE TABLE memories (
  id          UUID PRIMARY KEY,
  user_id     UUID REFERENCES users(id),
  workspace_id UUID REFERENCES workspaces(id),  -- added in Phase 4
  content     TEXT NOT NULL,
  embedding   vector(1536),
  source_conv UUID REFERENCES conversations(id),
  memory_type TEXT,   -- 'preference', 'entity', 'decision', 'fact'
  confidence  FLOAT,
  created_at  TIMESTAMPTZ,
  last_used   TIMESTAMPTZ,
  use_count   INT DEFAULT 0
);
```

**Extraction pipeline:**
1. Nightly background job: for each conversation since last run, call a summarization prompt that extracts structured memories. Prompt: *"Extract user preferences, named entities, decisions made, and factual assertions from this conversation. Output JSON array."*
2. Embed each extracted memory and upsert into `memories` table via pgvector.
3. Deduplicate against existing memories using cosine similarity (threshold: 0.92).

**Retrieval integration:**
1. At query time, retrieve top-K memories alongside document chunks.
2. Inject relevant memories into the system prompt under a `<memory>` section.
3. Update `last_used` and `use_count` on retrieval.

**Memory management UI:**
- `Settings → Memory` panel showing all stored memories
- Users can delete individual memories or clear all
- Show memory source conversation link

**Acceptance criteria:**
- Memory extraction runs nightly without blocking the main app
- Relevant memories surface in responses within 24h of a conversation
- Users can view and delete their memories
- Memory retrieval adds < 50ms to query latency (pgvector ANN search)

---

### Feature 2.3 — GraphRAG / Entity-Based Retrieval Layer

**Effort:** High | **Impact:** High

**What:** Extract named entities from documents on ingest and build a knowledge graph alongside the vector index. At query time, use graph traversal to expand retrieval context for entity-heavy, multi-hop questions.

**Why:** Vector + BM25 hybrid retrieval is excellent for passage-level similarity. It is weak for questions like "How does project X relate to team Y" or "What decisions involved both system A and system B" — questions that require reasoning over entity relationships rather than semantic proximity. A knowledge graph turns a document corpus into a navigable knowledge base.

**How:**

**Ingest pipeline addition:**
```
Document ingested
    │
    ├─► Chunker (existing)
    │       └─► pgvector
    │
    └─► Entity Extractor (new)
            └─► spaCy NER (en_core_web_trf)
            └─► Entity graph → Postgres JSONB or NetworkX persisted as adjacency list
```

**Graph schema (stored in Postgres):**
```sql
CREATE TABLE entities (
  id       UUID PRIMARY KEY,
  name     TEXT,
  type     TEXT,   -- PERSON, ORG, SYSTEM, PROJECT, LOCATION…
  aliases  TEXT[]
);

CREATE TABLE entity_relations (
  source_id UUID REFERENCES entities(id),
  target_id UUID REFERENCES entities(id),
  relation  TEXT,  -- 'mentioned_with', 'depends_on', 'owned_by'…
  doc_id    UUID REFERENCES documents(id),
  chunk_id  UUID REFERENCES chunks(id),
  weight    FLOAT  -- co-occurrence frequency
);
```

**Query-time expansion:**
1. Extract entities from the user query using the same NER model.
2. For each query entity, fetch related entities (1-hop) from `entity_relations`.
3. Use related entity names to construct additional BM25 queries.
4. Merge graph-expanded results with standard vector retrieval. Re-rank the combined set.

**Acceptance criteria:**
- Entity extraction runs synchronously during ingest (< 2s per document)
- Graph-expanded retrieval measurably improves precision on multi-entity test queries
- Entity graph is browsable via admin UI (basic entity list with relation counts)
- Graph and vector indices stay in sync on document deletion

---

## Phase 3 — Architecture (M6–M9)

**Theme:** Refactor the monolith into a composable agentic architecture. This is the largest structural change — it unlocks everything that follows and makes the platform extensible without core modifications.

### Feature 3.1 — MCP Server Split per Domain

**Effort:** High | **Impact:** High

**What:** Extract the three data-domain capabilities — local document retrieval, web search, and cloud platform connectors — into independently deployable MCP servers. The core application communicates with them exclusively via the MCP protocol.

**Why:** Currently all three capabilities are Python modules imported into the same process. This means a crash in the web search module can affect document retrieval, a new connector requires a core app restart, and horizontal scaling is all-or-nothing. MCP server separation gives each domain its own process, its own scaling policy, its own dependency graph, and its own failure boundary. Adding a new connector (SharePoint, Confluence, S3) becomes a matter of writing a new MCP server, not modifying the core.

**Target topology:**
```
LocalChat Core (Flask)
    │
    ├─── MCP ──► local-docs-server
    │                └─► pgvector, chunker, reranker
    │
    ├─── MCP ──► web-search-server
    │                └─► DuckDuckGo, Brave Search, Jina Reader
    │
    └─── MCP ──► cloud-connectors-server
                     └─► SharePoint, OneDrive, S3, Confluence
```

**How:**
1. Define the MCP tool schema for each server. Each exposes a `search(query, filters, top_k)` tool and a `list_sources()` tool.
2. Extract `rag/retrieval.py` into `mcp_server/local_docs/`. Wrap existing retrieval logic as MCP tool handlers.
3. Extract `rag/web_search.py` into `mcp_server/web_search/`. Add Brave Search as a second provider with automatic fallback.
4. Create `mcp_server/cloud_connectors/` as a new server. Start with a no-op stub that returns empty results — actual connectors land in Phase 4.
5. Update the core app to call MCP servers via `mcp_client.py` instead of direct imports. Use connection pooling and circuit breakers.
6. Add health checks per MCP server. Admin dashboard shows per-server status.
7. Update `docker-compose.yml` and `k8s/` manifests to deploy each server as a separate container.

**Migration path:** Run both old and new code paths in parallel behind a feature flag during transition. Validate output equivalence before cutting over.

**Acceptance criteria:**
- All three MCP servers deploy and run independently
- Core app retrieval results are identical before/after migration (verified via shadow mode)
- One MCP server can be restarted without affecting the others
- New MCP server can be added without modifying core app code

---

### Feature 3.2 — Aggregator Agent + Tool Routing

**Effort:** High | **Impact:** High

**What:** Add an explicit Aggregator Agent that sits between user input and tool execution. The agent receives the user query and planner output, dispatches tool calls to the appropriate MCP servers, handles retries and fallbacks, and synthesizes results before returning to the user.

**Why:** This is the keystone feature. Without it, tool dispatch is hardcoded in the RAG pipeline. With it, new tools are registered with the agent and automatically become available to any query type. It enables parallel tool calls, tool-level retries, and transparent orchestration that can be observed and debugged. Everything else — multi-model routing, memory integration, feedback — coordinates through this layer.

**How:**

```
User query + plan
    │
    ▼
┌─────────────────────────────────────────┐
│           Aggregator Agent              │
│                                         │
│  1. Parse plan → tool_calls list        │
│  2. Dispatch in parallel via MCP        │
│  3. Handle failures / retries           │
│  4. Merge + deduplicate results         │
│  5. Select synthesis model              │
│  6. Generate answer                     │
│  7. Attach citations                    │
└─────────────────────────────────────────┘
    │              │              │
    ▼              ▼              ▼
local-docs    web-search    cloud-connectors
  (MCP)         (MCP)           (MCP)
```

**Implementation options:**

| Option | Pros | Cons |
|---|---|---|
| LangGraph | Mature, debuggable, stateful | External dependency, abstractions can obscure |
| Custom ReAct loop | Full control, minimal deps | More code to maintain |
| LlamaIndex AgentWorker | Good MCP integration | Another large dependency |

**Recommendation:** Custom lightweight ReAct loop in `agent/aggregator.py` (~300 lines). Avoids heavy framework dependencies while staying fully auditable. Migrate to LangGraph if complexity grows beyond what the custom loop handles cleanly.

**Agent interface:**
```python
class AggregatorAgent:
    def __init__(self, mcp_clients: dict[str, MCPClient], model_router: ModelRouter):
        ...

    async def run(self, query: str, plan: Plan, session: Session) -> AgentResult:
        # Returns: answer, citations, tool_trace, model_used
        ...
```

**Acceptance criteria:**
- All retrieval goes through the agent; no direct MCP calls from Flask routes
- Parallel tool calls reduce multi-source query latency by ≥ 30%
- Tool trace is stored per conversation turn
- Agent handles MCP server downtime gracefully (returns partial results + warning)

---

### Feature 3.3 — Multi-Model Router

**Effort:** Medium | **Impact:** High

**What:** Add a routing layer that selects the optimal model for each query based on intent, complexity, and document type — rather than binding all queries to a single active Ollama model.

**Why:** A simple factual lookup ("what is the deadline for project X?") should not burn the same compute as a complex synthesis ("write a comparative analysis of all three vendor proposals"). Routing fast queries to a small fast model and complex queries to a large capable model makes the system both faster and cheaper without sacrificing output quality where it matters.

**How:**

**Routing taxonomy:**

| Query type | Signal | Model class |
|---|---|---|
| Simple factual lookup | Short query, single entity, no synthesis | Fast (e.g. `llama3.2:3b`) |
| Multi-document synthesis | Plan hops ≥ 2, synthesis_required: true | Large (e.g. `llama3.1:70b`) |
| Code generation / review | Query contains code, doc_type == code | Code (e.g. `qwen2.5-coder:14b`) |
| Image-heavy document | doc_type == image, PDF with figures | Vision (e.g. `llava:13b`) |
| Default | Anything else | Base (e.g. `llama3.1:8b`) |

**Implementation:**
1. Add `ModelRegistry` to `config/models.py`: maps model class → Ollama model ID + max_tokens + timeout.
2. Add `ModelRouter` to `agent/router.py`. Inputs: query text, plan JSON, retrieved doc types. Output: model class selection + rationale.
3. Router runs as a fast synchronous classification (rule-based first, optionally a tiny classifier model later).
4. The Aggregator Agent calls `model_router.select(query, plan, context)` before the synthesis step.
5. Add `model_used` to the API response and display it as a small badge in the chat UI.
6. Admin dashboard: per-model usage breakdown, latency distribution, fallback rates.

**Acceptance criteria:**
- Simple queries route to fast model (verified via response metadata)
- Code-focused queries route to code model
- Users can override model selection via a chat UI selector
- Model routing adds < 10ms to query latency (rule-based path)

---

## Phase 4 — Platform (M10–M12)

**Theme:** Turn LocalChat from a personal RAG tool into team-ready knowledge infrastructure. Add the self-improvement loop, multi-user support, and live data connectors that give it permanent competitive advantage.

### Feature 4.1 — Retrieval Feedback Loop + Adaptive Reranker ✅

**Effort:** Medium | **Impact:** High

**What:** Collect explicit user feedback on answers and retrieval quality. Use collected signal to fine-tune the reranker on domain-specific relevance. Surface aggregate quality metrics in the admin dashboard.

**Why:** After a few months of usage, LocalChat's reranker becomes domain-adapted in a way no out-of-the-box tool can match. A medical team's LocalChat learns what "relevant" means for clinical documents. An engineering team's LocalChat learns to surface architecture decision records over generic documentation. This is a durable moat — it compounds with use and cannot be replicated by a generic product.

**How:**

**Signal collection:**
```sql
CREATE TABLE answer_feedback (
  id           UUID PRIMARY KEY,
  conv_turn_id UUID REFERENCES conversation_turns(id),
  rating       SMALLINT,          -- 1 (thumbs up) / -1 (thumbs down)
  feedback_type TEXT,             -- 'answer_quality' | 'wrong_sources' | 'missing_source'
  correct_doc_ids UUID[],         -- user-indicated correct documents (optional)
  created_at   TIMESTAMPTZ
);
```

**Reranker fine-tuning pipeline:**
1. Weekly job: export feedback pairs from the past 7 days.
2. Construct training pairs: `(query, retrieved_chunk, label)` where label = 1 if chunk was in a positively-rated answer, 0 if in a negatively-rated one.
3. Fine-tune the cross-encoder reranker (e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2`) on domain pairs using sentence-transformers trainer.
4. Run evaluation on held-out pairs. If NDCG improves, swap the active reranker model.
5. Keep previous reranker versions. Rollback is one config change.

**Stale chunk detection:**
- Track retrieval frequency per chunk (`chunk_stats` table: retrieved_count, positive_feedback_count).
- Flag chunks with high retrieval frequency but zero positive feedback as potentially stale or noisy.
- Surface flagged chunks in admin dashboard for manual review or re-ingestion.

**Admin dashboard additions:**
- Answer quality trend (rolling 7-day thumbs up rate)
- Top-retrieved documents by positive/negative ratio
- Reranker version history + NDCG delta per version
- Stale chunk list with last-modified date

**Acceptance criteria:**
- Feedback UI present on all RAG answers (thumbs up/down + optional "wrong sources" flag)
- Reranker fine-tuning runs weekly without manual intervention
- Admin dashboard shows quality metrics within 24h of feedback collection
- Rollback to previous reranker takes < 1 minute

---

### Feature 4.2 — Workspace / Persona Mode ✅

**Effort:** Medium | **Impact:** High

**What:** Users can create named workspaces, each with its own document collection, system prompt, model selection, memory scope, and tool configuration. Switching workspaces is a single click.

**Why:** A single shared knowledge base is limiting for users who work across multiple projects or domains. A "NMBS project" workspace and a "Legal research" workspace should have completely separate document sets, different system prompts (tone, domain vocabulary, output format), and isolated memory. Workspaces also make LocalChat a viable team tool — shared workspaces can have their own members, documents, and quality metrics.

**How:**

**Data model additions:**
```sql
CREATE TABLE workspaces (
  id           UUID PRIMARY KEY,
  name         TEXT NOT NULL,
  description  TEXT,
  system_prompt TEXT,
  model_class  TEXT,   -- override default model routing
  owner_id     UUID REFERENCES users(id),
  created_at   TIMESTAMPTZ
);

-- FK additions to existing tables
ALTER TABLE documents         ADD COLUMN workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE conversations     ADD COLUMN workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE memories          ADD COLUMN workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE answer_feedback   ADD COLUMN workspace_id UUID REFERENCES workspaces(id);

CREATE TABLE workspace_members (
  workspace_id UUID REFERENCES workspaces(id),
  user_id      UUID REFERENCES users(id),
  role         TEXT,   -- 'owner' | 'editor' | 'viewer'
  PRIMARY KEY (workspace_id, user_id)
);
```

**API changes:**
- All document, conversation, and retrieval endpoints accept an optional `workspace_id` param.
- Default workspace is auto-created per user on registration.
- Workspace-scoped retrieval: queries only search documents within the active workspace.

**UI:**
- Workspace selector in the top nav (dropdown with workspace name + member count).
- "New workspace" flow: name, description, system prompt, initial document upload.
- Workspace settings: members, model override, system prompt editor.
- Per-workspace quality metrics in admin dashboard.

**Acceptance criteria:**
- Documents are strictly scoped to their workspace (no cross-workspace retrieval)
- Workspace switch takes < 200ms (no full page reload)
- Shared workspaces support viewer/editor/owner roles
- Memory is scoped per workspace

---

### Feature 4.3 — Live Connector Framework ✅

**Effort:** High | **Impact:** High

**What:** A connector framework that keeps the LocalChat knowledge base current automatically. Connectors watch external sources — local folders, SharePoint, OneDrive, S3, webhook endpoints — and trigger ingest when documents are added, modified, or deleted.

**Why:** Manual document upload is the biggest friction point in enterprise RAG adoption. If the knowledge base is stale, users stop trusting it. A connector to a team's shared drive or intranet turns LocalChat from "a tool I have to maintain" into ambient knowledge infrastructure that stays current without manual effort.

**How:**

**Connector interface:**
```python
class BaseConnector(ABC):
    """All connectors implement this interface."""

    connector_id: str
    display_name: str
    workspace_id: UUID

    @abstractmethod
    async def list_sources(self) -> list[DocumentSource]:
        """Return all documents visible to this connector."""
        ...

    @abstractmethod
    async def poll(self) -> list[DocumentEvent]:
        """Return new/modified/deleted events since last poll."""
        ...

    @abstractmethod
    async def fetch(self, source: DocumentSource) -> bytes:
        """Fetch raw document content."""
        ...
```

**Built-in connectors (Phase 4):**

| Connector | Mechanism | Notes |
|---|---|---|
| Local folder watcher | inotify (Linux) / FSEvents (macOS) / polling fallback | Watches a configured directory tree |
| SharePoint / OneDrive | Microsoft Graph API delta queries | Requires OAuth2 app registration |
| S3 / compatible | S3 ListObjectsV2 with `LastModified` polling | Works with MinIO, Cloudflare R2, etc. |
| Webhook receiver | HTTP POST endpoint | Generic; any system can push document events |

**Sync worker:**
1. Per-connector sync worker runs on a configurable interval (default: every 15 minutes for poll-based, real-time for inotify/webhook).
2. On `DOCUMENT_ADDED` / `DOCUMENT_MODIFIED`: download → run through type-aware chunker → upsert in pgvector + entity graph.
3. On `DOCUMENT_DELETED`: remove chunks, entities, and memory references. Mark conversations that cited the document.
4. Per-connector sync status shown in admin dashboard: last sync time, document count, error rate.

**Connector configuration (stored in Postgres):**
```sql
CREATE TABLE connectors (
  id            UUID PRIMARY KEY,
  workspace_id  UUID REFERENCES workspaces(id),
  connector_type TEXT,   -- 'local_folder' | 'sharepoint' | 'onedrive' | 's3' | 'webhook'
  config        JSONB,   -- connector-specific config (path, credentials ref, etc.)
  enabled       BOOLEAN DEFAULT true,
  sync_interval INT,     -- seconds
  last_sync_at  TIMESTAMPTZ,
  last_error    TEXT
);
```

**Credential handling:** Connector credentials (OAuth tokens, API keys) are never stored in `config`. They reference entries in a separate `secrets` table that is encrypted at rest.

**Acceptance criteria:**
- Local folder watcher detects and ingests new files within 30 seconds
- SharePoint connector syncs delta changes without full re-ingest
- Deleted documents are removed from the vector index within one sync cycle
- Connector sync failures do not affect the main application
- Admin dashboard shows sync status per connector

---

## Target Architecture

End-state architecture after all four phases:

```
┌─────────────────────────────────────────────────────────┐
│                        Frontend                          │
│  Chat UI │ Citation viewer │ CoT trace │ Workspace nav  │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTP / WebSocket
┌──────────────────────────▼──────────────────────────────┐
│                    Flask Core + API                      │
│              JWT auth │ Rate limiting │ Admin            │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                   Aggregator Agent                       │
│   Query planner │ Tool dispatcher │ Multi-model router   │
│   Memory retrieval │ Result synthesis │ Citation builder │
└──────┬───────────────────┬────────────────────┬─────────┘
       │ MCP               │ MCP                │ MCP
┌──────▼──────┐   ┌────────▼────────┐   ┌───────▼──────────┐
│ local-docs  │   │  web-search     │   │ cloud-connectors  │
│   server    │   │    server       │   │     server        │
│             │   │                 │   │                   │
│ Chunker     │   │ DuckDuckGo      │   │ SharePoint        │
│ Reranker    │   │ Brave Search    │   │ OneDrive / S3     │
│ GraphRAG    │   │ Jina Reader     │   │ Webhook receiver  │
└──────┬──────┘   └─────────────────┘   └───────────────────┘
       │
┌──────▼──────────────────────────────────────────────────┐
│                      Data Layer                          │
│  pgvector (HNSW) │ Knowledge graph │ Memory store        │
│  Feedback signals │ Conversation history │ Connector sync│
└─────────────────────────────────────────────────────────┘
```

---

## Effort vs. Impact Matrix

All 12 features plotted by implementation effort and user impact:

| Feature | Phase | Effort | Impact | Quadrant |
|---|---|---|---|---|
| Answer attribution + source viewer | 1 | Low | High | Quick win |
| Adaptive chunking per document type | 1 | Low | High | Quick win |
| Cloud model fallback | 1 | Low | Medium | Quick win |
| Query planner + CoT trace UI | 2 | Medium | High | Strategic bet |
| Long-term memory store | 2 | Medium | High | Strategic bet |
| GraphRAG / entity retrieval | 2 | High | High | Strategic bet |
| MCP server split | 3 | High | High | Strategic bet |
| Aggregator agent | 3 | High | High | Strategic bet |
| Multi-model router | 3 | Medium | High | Strategic bet |
| Retrieval feedback loop | 4 | Medium | High | Strategic bet |
| Workspace / persona mode | 4 | Medium | High | Strategic bet |
| Live connector framework | 4 | High | High | Strategic bet |

---

## Design Principles

These four principles govern every architectural and UX decision in this roadmap.

### 01 — Privacy-First by Default
Your data never leaves your infrastructure unless you explicitly configure a cloud fallback and explicitly mark a document as non-sensitive. All processing — chunking, embedding, retrieval, generation — runs locally. Cloud fallback is opt-in, per-document-type, and surfaced clearly in the UI.

### 02 — Transparent Intelligence
Every answer shows its sources. Every plan can be inspected. No black boxes. Users who understand what the system is doing can correct it when it is wrong, which makes the system more useful over time. The CoT trace panel, citation viewer, and connector sync status all serve this principle.

### 03 — Domain-Adapted Over Time
The feedback loop is not a nice-to-have — it is the mechanism by which LocalChat becomes permanently superior to any generic RAG tool for your specific corpus. After three months of use on an engineering team's documentation, the reranker has learned what "relevant" means for that team's queries in a way that cannot be replicated by a product trained on generic data.

### 04 — Composable Architecture
MCP boundaries exist so that every domain agent can be swapped, scaled, or extended without touching the core. A new cloud connector is a new MCP server, not a pull request to the main application. A new model provider is a new `ModelClient` implementation, not a change to the agent. Composability is what makes the platform extensible beyond this roadmap.

---

## Dependencies & Stack Decisions

### Core additions by phase

| Phase | Addition | Replaces / augments |
|---|---|---|
| 1 | LiteLLM | Direct Ollama client calls |
| 2 | spaCy `en_core_web_trf` | No prior NER |
| 2 | NetworkX (or Postgres JSONB graph) | No prior entity graph |
| 3 | MCP Python SDK | Direct Python imports between modules |
| 3 | LangGraph (optional) | Custom ReAct loop |
| 4 | `sentence-transformers` trainer | Static reranker model |
| 4 | Microsoft Graph SDK | No prior SharePoint/OneDrive |
| 4 | `watchdog` (Python) | No prior folder watching |

### Decisions to make before Phase 3

**Graph backend:** NetworkX is fast to prototype but does not persist across restarts without serialization. A Postgres JSONB adjacency list scales better for large corpora. Neo4j is the most capable but adds operational complexity. **Recommendation:** Postgres JSONB for Phase 2 prototype, revisit if graph query patterns become complex.

**Agent framework:** A custom ReAct loop (~300 lines) keeps dependencies minimal and the code fully auditable. LangGraph adds visual debugging and better state management at the cost of abstraction. **Recommendation:** Start custom, migrate to LangGraph when the agent exceeds 3 tool types or requires branching control flow.

**Reranker model:** `cross-encoder/ms-marco-MiniLM-L-6-v2` is fast (< 10ms per pair on CPU) and fine-tunable. `cross-encoder/ms-marco-electra-base` is more accurate but 4× slower. **Recommendation:** Start with MiniLM-L-6; benchmark on your corpus before upgrading.

### What this roadmap does not include

- **Multi-tenancy / SaaS mode:** Workspace mode in Phase 4 provides team support, but this roadmap assumes a self-hosted deployment. Multi-tenant SaaS would require a separate pricing, billing, and isolation layer.
- **Mobile client:** Out of scope. The web UI is responsive but a native mobile app is a separate workstream.
- **Fine-tuning base LLMs:** The feedback loop fine-tunes the reranker only. Fine-tuning the generative model on your corpus is a significant additional undertaking that would require GPU infrastructure beyond what a typical local deployment provides.
- **Real-time collaboration:** Workspaces support shared access but not simultaneous real-time editing of documents or conversations.

---

*Last updated: April 2026*
*Repository: https://github.com/jwvanderstam/LocalChat*
