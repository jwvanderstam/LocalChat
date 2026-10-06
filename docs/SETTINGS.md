# Settings Reference

Per-parameter descriptions for the RAG retrieval/reranking controls on the
Settings page. This file is the single source for that text — the settings
page pulls each section below in as a fragment via `DocsService` instead of
duplicating the wording in `templates/settings.html`, so the two cannot
drift apart.

## Retrieval candidates (TOP_K_RESULTS)

How many candidates retrieval considers: the semantic arm fetches twice this from
the vector index, the lexical arm this many from full-text search, and the two are
blended before filtering. Higher values improve recall but add a few ms of latency.

## Chunks sent to LLM (RERANK_TOP_K)

Must be &le; TOP_K_RESULTS. The best this many candidates are kept, rescored by
the cross-encoder reranker when it is enabled, and any it plainly rejects are
dropped. Higher values give the LLM more evidence but consume more context window
and slow generation slightly.

## Diversity threshold (DIVERSITY_THRESHOLD)

Jaccard word-overlap threshold for near-duplicate filtering: a candidate sharing
more than this fraction of its words with one already chosen is skipped. Lower
values prune more aggressively — can hurt domain docs where chapters share
vocabulary.

## Semantic weight (SEMANTIC_WEIGHT)

Blend of semantic cosine similarity vs. lexical (Postgres tsvector full-text)
score in hybrid search; the lexical arm matches chunks containing any of the
question's content words. Increase for conceptual queries; decrease for
exact-term lookups.
