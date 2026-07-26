# Settings Reference

Per-parameter descriptions for the RAG retrieval/reranking controls on the
Settings page. This file is the single source for that text — the settings
page pulls each section below in as a fragment via `DocsService` instead of
duplicating the wording in `templates/settings.html`, so the two cannot
drift apart.

## Retrieval candidates (TOP_K_RESULTS)

Initial number of chunks fetched from the vector index before reranking.
Higher values improve recall but add a few ms of latency.

## Chunks sent to LLM (RERANK_TOP_K)

Must be &le; TOP_K_RESULTS. Higher values give the LLM more evidence but consume
more context window and slow generation slightly.

## Diversity threshold (DIVERSITY_THRESHOLD)

Jaccard similarity threshold for duplicate-chunk filtering. Lower values prune
more aggressively — can hurt domain docs where chapters share vocabulary.

## Semantic weight (SEMANTIC_WEIGHT)

Blend of semantic cosine similarity vs. lexical (Postgres tsvector full-text)
score in hybrid search. Increase for conceptual queries; decrease for
exact-term lookups.
