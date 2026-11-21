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
   *Done in #558 (2026-11-21).* The cause was two ranking bugs, not the loaders: a chunk only the
   lexical search found was scored as semantic 0.0, and the reranker scored only the top 12 by
   blended score (it now scores up to `RERANK_CANDIDATES`, 36). Retrieval only, 105 questions:

   | | before → after |
   |---|---|
   | answer passage reaches the model | 0.50 → 0.64 (52 → 67 questions) |
   | Recall@1 | 0.41 → 0.50 |
   | Recall@5 | 0.57 → 0.70 |
   | MRR | 0.48 → 0.59 |
   | PowerPoint, in context | 0.40 → 0.73 |
   | Excel, in context | 0.35 → 0.59 |
   | Word, in context | 0.48 → 0.65 |
   | PDF, in context | 0.58 → 0.62 |

   Median retrieval went from 0.54 s to 1.46 s on CPU.
2. **Use a ~14B model.** `qwen2.5:14b` fits a 12 GB card; a 3B model loses about 15 points even
   when the answer is in front of it.
3. **Replace the eval judge** before using `answer_correct` to steer anything: a 7B judge cannot
   separate a correct answer from a partial one. A stronger judge needs its own calibration.
   *Done differently (2026-11-21): the judge prompt was the failure, not the model.* Re-graded
   against the same 104 blind grades (52 cases × two models). Each v3 judge failed to give a
   parseable reply on one answer, and not the same one (mistral on a llama3.2 answer, qwen2.5:14b
   on a qwen2.5:14b answer to another question), so each v3 row is over 103:

   | Judge | n | Exact | Bias |
   |---|---|---|---|
   | mistral, v2 (context in the prompt) | 104 | 0.27 (28) | −0.30 |
   | qwen2.5:14b, v2 | 104 | 0.78 (81) | 0.00 |
   | qwen2.5:14b, v3 | 103 | 0.82 (84) | −0.06 |
   | **mistral, v3** | **103** | **0.85 (88)** | **+0.07** |

   On a three-point scale, agreement within one grade is near-automatic (only yes against no
   misses it), so it is not reported. The calibration is in-sample: v3 was written from the
   failures read off these same grades and chosen on them, with no held-out set, so 0.85 is an
   upper bound. qwen2.5:14b's untuned v2 at 0.78 suggests most of the gain is real.

   v3 grades `correct` in a call of its own against the reference alone, and rules out extra
   detail as a reason to lower the grade. mistral v3 is now the default: the best agreement, and a
   different model family from the answer model. It is slightly lenient, more so on the weaker
   model's answers, so it compresses the gap between models (0.07 against the blind 0.16).
   `faithfulness` still comes from v2's check, which these grades do not calibrate. The committed
   `answer_baseline.json` still records v1; re-baselining it with v3 and #558's retrieval is the
   follow-up.
4. **Answer prompt**: ask for complete, specific answers rather than concise ones (#556). On
   2026-11-21 it took `llama3.2`'s median answer from 45 to 128 words, with refusals down from
   18 to 14 of 105. For `qwen2.5:14b`, on the same retrieval (before #558), graded by mistral v3.
   The new-prompt run has no grade for one case (an unparseable judge reply, the passage in
   context), so the paired comparison covers 104 of 105 questions and 51 of the 52 in context:

   | qwen2.5:14b | old prompt | new prompt |
   |---|---|---|
   | Median words (middle half) | 41 (15–64) | 96 (59–157) |
   | Refusals | 23 | 17 |
   | `answer_correct`, 104 paired | 0.66 | 0.75 (16 better, 2 worse) |
   | `answer_correct`, 51 paired with the passage in context | 0.97 | 0.99 |
   | `faithfulness` | 0.63 | 0.76 |

   The gain is almost all in questions whose passage was not retrieved, where a longer answer
   gathers part of the reference from neighbouring passages; v3 is lenient on such answers, so
   read it as a direction. The prompt's "say what the documents do not cover" is mostly ignored:
   of the 36 answers given without the passage (53 questions, 17 refusals), 4 named a gap.
5. **Passage order** (2026-11-21, measured before #558, `qwen2.5:14b` answering under #556's
   prompt, graded by mistral v3): the context reaches the model in alphabetical order
   (`src/rag/retrieval.py`, the final `sorted(... filename, chunk_index)`). Relevance order made
   no measurable difference: `answer_correct` 0.745 alphabetical against 0.729 by relevance,
   3 cases better and 5 worse of 104 paired (the same case ungraded), and in no case did the
   order decide whether the passage fit the context budget. Left as it is.

## Setup note

A freshly created eval database needs `alembic upgrade head` after `db.initialize()`; without
it every ingest fails on `document_chunks.deleted_at`, because `_ensure_extensions_and_tables()`
builds only the base schema.
