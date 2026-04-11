# LocalChat Roadmap

LocalChat exists to be the gold standard for local, privacy-preserving knowledge management — an agentic RAG system that learns from every interaction and improves its own retrieval quality over time.

---

## What's in v1.0

| Capability | Details |
|---|---|
| RAG pipeline | Hybrid semantic + BM25 search, adaptive chunking, answer attribution |
| Vector store | PostgreSQL + pgvector (HNSW indexing) |
| LLM integration | Ollama with function-calling, multi-model routing, cloud fallback |
| Agentic layer | Aggregator agent, query planner, GraphRAG expansion, long-term memory |
| MCP architecture | Three independent MCP servers (local-docs, web-search, cloud-connectors) |
| Connectors | Local folder, S3/R2, SharePoint, OneDrive, webhook — live delta sync |
| Multi-user | JWT auth, workspace isolation, RBAC (viewer/editor/owner), Microsoft OAuth2 |
| Reranker | Cross-encoder re-ranking with optional weekly fine-tune on user feedback |
| Observability | Prometheus metrics, GPU monitoring, admin dashboard, Grafana dashboard |
| Deployment | Docker Compose, Helm chart (PostgreSQL + Redis StatefulSets, MCP servers) |

---

## Planned

### v1.1 — Quality & Reach
- Multi-language document support
- Confluence and Google Drive connectors
- Answer confidence scores surfaced in the UI
- Scheduled document re-ingestion for stale sources

### v1.2 — Collaboration
- Shared workspaces with real-time presence
- Annotation layer: highlight source chunks directly in documents
- Export: structured answers with citations to PDF/DOCX

### v1.3 — Intelligence
- Automatic ontology extraction per workspace (GraphRAG expansion)
- Active learning loop: model suggests which documents to ingest next
- Cross-workspace retrieval for shared knowledge bases

---

## Design Principles

1. **Local first** — no data leaves the machine without explicit configuration
2. **Graceful degradation** — every optional dependency (Redis, reranker, cloud fallback) degrades silently
3. **Composable** — each MCP server is independently deployable; new connectors require zero changes to core retrieval
4. **Observable by default** — every request carries a trace ID; all slow paths are logged and metered
5. **Test everything** — no feature ships without unit tests; no integration path ships without an integration test
