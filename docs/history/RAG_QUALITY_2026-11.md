# What limits answer quality — findings of 2026-11-20

The question: after roughly 600 PRs on code quality, answers are still short and of limited
intelligence. Is the limit horsepower, code, or something else?

**Answer: retrieval first, model size second, prompt third. Code quality is not the limit.**
The PRs made LocalChat safe and correct to run; none of them could make answers smarter.

## Method

`scripts/eval_answers.py run` on the private P2-3 corpus (208 documents, 105 accepted cases),
freshly ingested into a throwaway database, answered twice on identical retrieval:

| | |
|---|---|
| Answer models | `llama3.2` (3B) and `qwen2.5:14b`, both Q4, on an RTX 5070 (12 GB) |
| Judge | `mistral` (7B), judge prompt v2 |
| Retrieval | repository defaults (`TOP_K_RESULTS` 30, `RERANK_TOP_K` 12, `CHUNK_SIZE` 1200, `MAX_CONTEXT_LENGTH` 24576) |
| Answer prompt | the prompt as it stood on `main` (7ebcf50) |

No prompt was truncated: Ollama logged no truncation at `num_ctx` 8192.

Because the automated judge turned out not to discriminate (below), the 52 cases where the
proof passage reached the model were also graded **blind** by an AI assistant (Claude): each
pair of answers shuffled as A/B, graded yes / partial / no against the reference, then unblinded.
One grader, grading against the reference rather than the full context, who had seen five of
the 52 cases unblinded beforehand.

The cases and answers quote the private corpus and stay outside the repository; only aggregates
are recorded here.

## Results

### Retrieval: the answer reaches the model in half the questions

| Metric | Value |
|---|---|
| `source_recall@1` | 0.41 |
| `source_recall@5` | 0.571 |
| `proof_recall` (the proof passage is in the context) | **0.495** |
| `citation_correct` | 0.581 |

Identical for both models — retrieval does not depend on the answer model. On the previous run
(2026-09-30) misses concentrated in office formats: the source was not retrieved for 76% of
Excel, 67% of PowerPoint and 52% of Word questions, against 20% for PDF.

When the proof was missing, the models refused only 17 (llama3.2) and 22 (qwen2.5:14b) of 53
times; otherwise they answered from whatever was retrieved.

### Model size: decisive once the answer is in context

Blind grades, 52 cases with the proof in context:

| | Mean | Yes | Partial | No |
|---|---|---|---|---|
| llama3.2 (3B) | **0.80** | 37 | 9 | 6 |
| qwen2.5:14b | **0.95** | 48 | 3 | 1 |

qwen2.5:14b won 13 cases and lost none. llama3.2's failures were the typical small-model ones:
answering from a neighbouring chunk, latching onto a related fact, inventing a detail.

### The automated judge cannot measure this

| | llama3.2 | qwen2.5:14b |
|---|---|---|
| `answer_correct` (mistral, v2) | 0.495 | 0.490 |
| `faithfulness` (mistral, v2) | 0.536 | 0.591 |
| Same grade on a case | 91 of 105 | |

The mistral judge agreed with the blind grade on **28 of 104** answers. It grades verbatim-correct
answers "partial", claiming a figure or clause number is missing when it is present. Every
`answer_correct` recorded so far, including `tests/eval/answer_baseline.json`, is therefore
mostly judge noise; read it as a regression tripwire at best.

### Prompt: terseness is the prompt, not the model

Under the prompt then on `main` ("Answer directly and concisely…", temperature 0.0), both models
answered in a median of about 45 words. A larger model did not make answers longer.

## What follows

1. **Retrieval of office formats** is the largest remaining gain: about half of all questions
   never give the model the passage that answers them.
2. **Use a ~14B model.** `qwen2.5:14b` fits a 12 GB card; a 3B model loses about 15 points even
   when the answer is in front of it.
3. **Replace the eval judge** before using `answer_correct` to steer anything: a 7B judge cannot
   separate a correct answer from a partial one. A stronger judge needs its own calibration.
4. **Answer prompt**: ask for complete, specific answers rather than concise ones (tried on the
   live stack on 2026-11-20, branch `rag/answer-prompt`, not yet measured).
5. Smaller, untested: the context reaches the model in alphabetical order
   (`src/rag/retrieval.py`, the final `sorted(... filename, chunk_index)`), not by relevance.

## Setup note

A freshly created eval database needs `alembic upgrade head` after `db.initialize()`; without
it every ingest fails on `document_chunks.deleted_at`, because `_ensure_extensions_and_tables()`
builds only the base schema.
