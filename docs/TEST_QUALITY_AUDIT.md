# Test Quality Audit (Mutation Testing)

Coverage percentage measures execution, not verification — a line can run inside
a test with zero assertions on its actual behavior and still count as "covered."
This audit uses **mutation testing** instead: deliberately introduce small bugs
into source (flip a comparison, change a boundary, drop a negation, typo a dict
key) and check whether any test fails. A mutant that **survives** (no test
fails) means that code path executes under test but nothing verifies it —
ground truth for weak tests, not a vibe-based read of the test file.

Tool: [`mutmut`](https://mutmut.readthedocs.io/). Audited 2026-07-16/17.

## Environment notes (read before re-running)

- **`mutmut` 3.x does not work on this codebase.** Its coverage-instrumentation
  ("trampoline") mechanism asserts a mutated module's name never starts with
  `src.` — it collides with this repo's `src.`-prefixed imports, which are used
  inside test method bodies (not just at file top) in the majority of unit test
  files. This is a hard incompatibility, not a config problem. **Use `mutmut<3`
  (2.5.1 tested)** — it mutates in place and runs a plain `pytest` command, no
  import-layout assumptions.
- **`mutmut` is not installable natively on Windows** (`mutmut<3` works fine;
  `mutmut>=3` refuses to run outside WSL entirely). Run it in a Linux container:
  ```bash
  docker run -d --name mutmut-runner -v "$(pwd):/app" -w /app python:3.12-slim sleep infinity
  docker exec mutmut-runner bash -c "pip install -q -r requirements.txt 'mutmut<3'"
  ```
- **Never bind-mount the live working tree for a `mutmut<3` run.** It mutates
  the real file on disk and reverts it after each mutant; if the process is
  killed mid-mutant (e.g. an interrupted `docker exec`), the mutation is left
  on disk. Use an isolated `git worktree` instead:
  ```bash
  git worktree add --detach ../LocalChat-mutmut main
  docker run -d --name mutmut-runner -v "/path/to/LocalChat-mutmut:/app" -w /app python:3.12-slim sleep infinity
  # ... run mutmut against /app inside the container ...
  git worktree remove --force ../LocalChat-mutmut   # when done
  ```
- **Scope `--paths-to-mutate` and `--runner` to one module + its dedicated test
  file(s) at a time**, not the whole repo. A blind whole-repo run against
  ~20K LOC would take hours; scoping to one module's own tests brings it to
  seconds-per-mutant. Before trusting a scoped run, grep for any *other* test
  file that imports the module, and check whether it exercises the real
  implementation or only patches/mocks it out (mocked usages don't affect the
  mutation result and can be safely excluded from the runner).
- **Run one module fully to completion before starting the next.** `mutmut<3`
  stores results in a `.mutmut-cache` file in the current directory; starting
  a second run before reading the first's results clears the cache out from
  under it.
- Log-message-only mutations (`f"text"` → `f"XXtextXX"` inside a `logger.debug`/
  `.info` call, or an off-by-one in a message-truncation slice) routinely
  survive and are **not worth chasing** — asserting on exact log text is itself
  an anti-pattern (`WEAK-COUPLED`: breaks on a valid refactor). They're noted
  below only to separate them from the mutants that represent real gaps.

## Method

1. `mutmut run` scoped to a module + its real (non-mocked) test file(s).
2. `mutmut results` for the kill-rate summary; `mutmut show <id>` per survivor.
3. Read the actual test file(s) to map each surviving mutant to *why* the
   existing test didn't catch it, using this rubric:
   - **STRONG** — asserts a specific expected value/state change that would
     fail under the mutation.
   - **WEAK-SMOKE** — checks "no exception," "not None," a status code, or a
     return type; passes regardless of the actual computed value.
   - **WEAK-MOCKED** — mocks so much of the unit that the test verifies the
     mock was called, not that real logic produced the right output.
   - **MISSING-NEGATIVE-SPACE** — only exercises one representative value of a
     set/branch, never the others (e.g. one member of a 6-value set, or only
     one side of a boundary).

## Findings by module

Ranked by how much real verification risk the gaps carry, worst first.

### `src/rag/scoring.py` (BM25Scorer) — 3/84 killed (3.6%)

**Severe.** All 6 existing tests for `BM25Scorer` (across `test_rag_additional.py`,
`test_rag_comprehensive_v2.py`, `test_rag_edge_cases.py`) only construct the
object and check `scorer.k1`/`scorer.b` constructor storage. **None ever call
`.fit()` or `.score()`.** The entire ~80-line algorithm — tokenization, IDF
computation, the empty-corpus early-return guard, `doc_idx` bounds checking,
the BM25 score formula itself — has zero behavioral verification. Confirmed
real, not a scoping artifact: mutating the empty-corpus guard
(`if self.corpus_size == 0` → `!=`) and the bounds check
(`0 <= doc_idx < len(...)` → `1 <= doc_idx`) both survive outright, and both
are real bugs a caller could hit.

**Needed:** tests that call `fit(corpus)` on a real small corpus and assert on
`idf`, `doc_freqs`, `avgdl`; a test with an empty corpus; a test for `score()`
with `doc_idx=0` explicitly (the mutated boundary); a test verifying that two
documents with different term frequencies for the same query produce different,
correctly-ordered scores (BM25's actual purpose).

### `src/tools/executor.py` (ToolExecutor) — 63/124 killed (49%)

**High risk, concentrated in two places:**

- `_format_data_as_text` (static formatter, ~15 lines) has 5 tests, but all use
  `in` substring assertions (`"Revenue" in result`) instead of exact equality.
  Every mutation to padding, key-formatting (`.replace("_", " ")`), recursion
  depth (`indent + 1` → `indent - 1`), and list-join separator survives because
  the substring the test checks for is still present regardless of surrounding
  formatting. No test key contains an underscore, so `.replace("_", " ")` is a
  no-op in every test case that exercises it.
- Several dict-key typos in constructed messages survive, e.g. `"role"` →
  `"XXroleXX"` when appending a tool-result message to the conversation, and
  `props.get("type")` → `props.get("XXtypeXX")` in schema-mismatch detection —
  both would break real behavior (a malformed message sent to the LLM; a
  bypassed validation check) but no test asserts on the exact structure of
  these dicts.

**Needed:** exact-equality assertions for `_format_data_as_text` (including an
underscore-containing key and a 2-level-deep nested structure with a specific
expected indent string), and a test that inspects the actual message dict
appended in inline-mode rather than just the returned text.

### `src/rag/planner.py` (QueryPlanner) — 63/75 killed (84%)

**Moderate**, two real gaps:
- `_parse()`'s JSON key lookups: every test payload passes `"tools": ["local_docs"]`
  explicitly — which is also the fallback default used when the key is missing
  or misspelled. `data.get("tools")` → `data.get("XXtoolsXX")` survives because
  the fallback produces the identical result every test expects. Same story for
  `synthesis_required`'s default-when-absent-value (`False` → `True`): no test
  ever omits the key.
- `plan()`'s LLM call: the mocked `ollama_client.generate_chat_response` always
  yields exactly one chunk, so `raw += chunk` (correct, accumulates) and
  `raw = chunk` (bug, keeps only the last chunk) are indistinguishable. The
  system prompt sent to the LLM (`messages[0]["content"]`) is never asserted on
  at all, nor is the `"content"` key name in either message dict.
- (Also: several log-string-only mutations — not real gaps, see environment notes.)

**Needed:** a test with a mocked multi-chunk async generator; a test overriding
`"tools"` to a non-default value; a test whose JSON omits `synthesis_required`;
an assertion on the actual system-prompt content sent.

### `src/graph/expander.py` (QueryExpander) — 13/24 killed (54%)

**Moderate.** `_KEEP_TYPES`-and-length entity filter
(`ent.label_ in _KEEP_TYPES and 2 <= len(text) <= 200`) has a length-boundary
test only at the low end (a 1-char entity), never at the upper boundary (200,
201 chars) or the exact lower boundary (2 chars) — all four boundary mutants
(`2`→`3`, both `<=`→`<`, `200`→`201`) survive. Worse: `and` → `or` between the
label check and the length check also survives — no test provides an entity
with a disallowed label but valid length (or vice versa) to prove the two
conditions are actually ANDed. `max_extra`'s default value (5) is never tested
— the one test for it always passes `max_extra=3` explicitly.

**Needed:** boundary tests at exactly 2, 200, and 201 chars; a disallowed-label
+ valid-length case; a default-`max_extra` test with no explicit override.

### `src/agent/router.py` (ModelRouter) — 55/60 killed (91.7%)

**Low risk — the strongest file audited**, useful as the positive example.
`TestIsFast`'s precise boundary pair (80 chars → fast, 81 chars → not fast) is
why every mutation to that comparison died. The gaps that remain: `_IMAGE_DOC_TYPES`/
`_CODE_DOC_TYPES` are 2- and 6-member sets respectively, but tests only sample
one member of each (`"IMAGE"`, `"CODE_PYTHON"`) — the lowercase variants and
`"CODE_TS"` are never exercised. One rationale-content assertion
(`test_rationale_includes_class_name`) is tautological: `select()`'s rationale
string always embeds `cls.value` by construction, so the assertion
(`any(cls in rationale for cls in [...])`) passes for *any* correctly-classified
result, not just the correct one.

## What this does and doesn't cover

Five modules were audited (out of 91 unit test files) — chosen for algorithmic
complexity where weak tests carry real risk, not a representative sample of the
whole suite. Extending this to more modules is mechanical now that the
environment/scoping approach above is worked out; the main cost is the
scoping-verification step (confirming no other test file exercises the target
module's real implementation) and picking targets where mutation survivors
would actually matter — a getter/property-heavy module isn't worth the time a
branch-heavy scoring/filtering module is.
