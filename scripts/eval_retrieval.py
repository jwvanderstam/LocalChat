"""DEL-2 — measure retrieval quality against a fixed set of question/source pairs.

The ticket asks whether GraphRAG's 1-hop expansion earns its place. That is not
a question inspection can answer, and it is not a question a single anecdote can
answer either: it needs the same questions asked of the same corpus with the
feature on and off, and a number at the end.

    python scripts/eval_retrieval.py --ingest --compare graph

What it measures, per configuration:

  recall@1   the expected document is the top hit
  recall@5   it is somewhere in the top five
  MRR        1/rank of the first correct hit, averaged — rewards being right
             *and* being confident, which recall@k alone does not

Scoring is by SOURCE FILE, not by chunk. Asking which chunk "should" have won
would encode a judgement nobody made; asking whether the answer came from the
right document is the question a reader actually has.

Scoring is by relevance — each file's best chunk score — not by position:
retrieve_context returns its results in reading order, alphabetical by file
name, so until 2026-10-04 recall@1 and MRR here measured the alphabet.

It has two uses, and they answer different questions.

  Is retrieval good? Run it against a real embedding model, before and after a
  change to the RAG path, an embedding model or the reranker, and record both.
  A stubbed model cannot answer this: the numbers would measure the stub.

  Did this change move the ranking? (EV-1, the `retrieval-gate` CI job)

      python scripts/eval_retrieval.py --fake-ollama --ingest --check

  The stub embeds text as a bag of words, so with the model held fixed any
  movement in the score was caused by the diff — the hybrid blend, chunking,
  the lexical arm, filters, expansion. The comparison against
  tests/eval/baseline.json is exact. Blind to semantics beyond word overlap and
  to embedding-model changes, which stay with P2-3.

`--compare graph` has a trap worth knowing about. GRAPH_RAG_ENABLED governs two
different things: entity extraction *at ingest*, and 1-hop expansion *at query
time*. This script can only flip the second, because the first already happened.
So the corpus must be ingested with GRAPH_RAG_ENABLED=true, or the "on" arm
expands against an empty entity table, scores identically to "off", and the
comparison quietly returns the answer "no effect" no matter what the truth is —
a rigged verdict that looks like a measurement.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
# The sibling eval_answers.py owns relevance ranking and the settings pin; scripts/ is not a
# package, so it is reached by path rather than duplicated.
sys.path.insert(0, str(REPO_ROOT / "scripts"))

DEFAULT_CASES = REPO_ROOT / "tests" / "eval" / "retrieval_cases.yaml"
DEFAULT_BASELINE = REPO_ROOT / "tests" / "eval" / "baseline.json"
GATE_METRICS = ("recall@1", "recall@5", "mrr")


@dataclass
class Case:
    question: str
    source: str
    proof: str
    answered_by: str


def load_cases(path: Path) -> list[Case]:
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Case(**c) for c in raw["cases"]]


def resolve_source(source: str, corpus: Path) -> Path | None:
    """Where a case's source file actually is, or None if nowhere.

    Repo-relative first, so the in-tree docs cases keep resolving exactly as
    they did. A corpus outside the repo — the maintainer-supplied document set
    DEL-2 asks for — names its sources by bare filename instead.
    """
    for candidate in (REPO_ROOT / source, corpus / source):
        if candidate.exists():
            return candidate
    return None


def source_text(path: Path) -> str:
    """The text a source contributes, as the ingest sees it.

    Not read_text(): a .pptx/.xlsx/.docx source is a zip, and its proof string
    lives in the extracted text rather than in the bytes. Going through the
    chunker also makes the premise check verify something it otherwise would
    not — that the loader can extract this file at all. A binary that yields
    nothing would otherwise ingest as zero chunks and quietly drag the score
    down, which is the failure the proof guard exists to make loud.
    """
    from src.rag.processor import doc_processor

    ok, err, chunks, raw, _type, _version = doc_processor._load_document_chunks(  # noqa: SLF001
        str(path), path.name, path.suffix.lower(), None
    )
    if not ok or chunks is None:
        raise ValueError(err)
    return raw or "\n".join(c["text"] for c in chunks)


def verify_premises(cases: list[Case], corpus: Path) -> list[str]:
    """Check every case still describes the corpus.

    A pair whose source was rewritten stops being a retrieval question and
    becomes an unanswerable one — and it drags the score down silently, which
    reads as a regression in the retriever rather than rot in the fixture.
    """
    problems = []
    for case in cases:
        path = resolve_source(case.source, corpus)
        if path is None:
            problems.append(f"{case.source}: file is gone")
            continue
        try:
            text = source_text(path)
        except Exception as exc:  # noqa: BLE001 — an unreadable source is a rotted premise
            problems.append(f"{case.source}: could not extract text ({exc})")
            continue
        if case.proof not in text:
            problems.append(f"{case.source}: proof {case.proof!r} no longer present")
    return problems


def connect_db() -> None:
    """Bring up the pool and schema, as bootstrap_app() does for the server.

    Importing doc_processor is not enough: the Database singleton stays
    unconnected until initialize() runs, and every call then raises
    DatabaseUnavailableError rather than failing at import.
    """
    from src.db import db

    ok, message = db.initialize()
    if not ok:
        raise SystemExit(f"database unavailable: {message}")

    # And the migrations. _ensure_extensions_and_tables() creates the base
    # tables; every additive column since (document_chunks.deleted_at among
    # them) lives in Alembic, so initialize() alone leaves a schema the
    # queries do not match. bootstrap_app() runs both, and so must this.
    from src.app_bootstrap import _run_alembic_migrations

    _run_alembic_migrations()


def ingest_corpus(corpus: Path, workspace_id: str | None) -> int:
    """Ingest every file the application itself can ingest.

    This globbed `*.md` until 2026-08-31, which made the `--corpus` flag a
    promise the script could not keep: DEL-2's own next step is a run against
    a maintainer-supplied document set, and any real one is .pdf/.docx/.pptx.
    Those ingested as zero documents and scored against an empty database.
    """
    from src import config
    from src.rag.processor import doc_processor

    # rglob, not iterdir: a real document set lives in folders. iterdir read only the top
    # level, so a corpus of 274 files in subfolders ingested as 4, and every case whose
    # source sat in a subfolder was scored against a database that never held it.
    supported, skipped = [], []
    for path in sorted(corpus.rglob("*")):
        if not path.is_file():
            continue
        (supported if path.suffix.lower() in config.SUPPORTED_EXTENSIONS else skipped).append(path)

    # Named, not counted: a corpus silently two files smaller than the
    # maintainer thinks it is produces a score nobody can reproduce.
    for path in skipped:
        print(f"  - skipped {path.name}: {path.suffix or '(no extension)'} is not a supported type")

    count = 0
    for path in supported:
        try:
            ok, message, _ = doc_processor.ingest_document(
                str(path), workspace_id=workspace_id
            )
            if ok:
                count += 1
            else:
                print(f"  ! {path.name}: {message}")
        except Exception as exc:  # noqa: BLE001 — one bad file must not end the run
            print(f"  ! {path.name}: {exc}")
    return count


def score(cases: list[Case], top_k: int, workspace_id: str | None) -> dict[str, Any]:
    from eval_answers import relevance_rank

    from src.rag.processor import doc_processor
    from src.utils.scope import ALL_WORKSPACES

    hits_at_1 = 0
    hits_at_5 = 0
    reciprocal = 0.0
    misses: list[tuple[str, str]] = []

    for case in cases:
        # --workspace-id is optional for a maintainer's own corpus; without it the run
        # scores the whole database, as it always has.
        results = doc_processor.retrieve_context(
            case.question, top_k=top_k, scope=workspace_id or ALL_WORKSPACES
        )
        # Ranked by each file's best chunk score, not by position: retrieve_context returns
        # its results in reading order, alphabetical by file name, so position measured the
        # alphabet. eval_answers.py found and fixed this for P2-3; this script had it too.
        scored = [
            (r.filename, r.metadata["rerank_score"] if r.metadata.get("rerank_score") is not None
             else r.metadata.get("combined_score", r.similarity))
            for r in results
        ]
        rank = relevance_rank(case.source, scored)
        if rank is not None:
            reciprocal += 1.0 / rank
            if rank == 1:
                hits_at_1 += 1
            if rank <= 5:
                hits_at_5 += 1
        else:
            top = max(scored, key=lambda pair: pair[1])[0] if scored else "(nothing)"
            misses.append((case.question, Path(top).name))

    n = len(cases)
    return {
        "n": n,
        "recall@1": hits_at_1 / n,
        "recall@5": hits_at_5 / n,
        "mrr": reciprocal / n,
        "misses": misses,
    }


def graph_expansion_reach(cases: list[Case]) -> tuple[int, int]:
    """How many of the questions the expander actually adds terms to.

    Checking that entities *exist* is not enough, and finding that out cost a
    wrong verdict: with 76 entities stored, the on/off comparison still came
    back at exactly +0.000 on all three metrics — because 0 of 20 questions
    matched an indexed entity, so expansion never contributed a single term.
    A delta of zero then means "never ran", not "did not help", and the two
    are indistinguishable in the score.

    The entities extracted from prose about software are codenames — SEC-1,
    RBAC-1, PG-0, LESSONS_LEARNED — and a natural-language question contains
    none of them. That is a real limit on the feature's reach, but it is not
    the question DEL-2 asks.
    """
    try:
        from src.db import db
        from src.graph.expander import QueryExpander

        expander = QueryExpander()
        fired = sum(1 for c in cases if expander.expand(c.question, db))
        return fired, len(cases)
    except Exception:  # noqa: BLE001 — no graph, no reach
        return 0, len(cases)


def report(label: str, result: dict[str, Any], show_misses: bool) -> None:
    print(f"\n  {label}")
    print(f"    recall@1  {result['recall@1']:6.1%}")
    print(f"    recall@5  {result['recall@5']:6.1%}")
    print(f"    MRR       {result['mrr']:6.3f}   ({result['n']} questions)")
    if show_misses and result["misses"]:
        print(f"    missed {len(result['misses'])}:")
        for question, got in result["misses"]:
            print(f"      - {question[:64]:<64} top hit: {got}")


def start_fake_ollama() -> Any:
    """Serve embeddings from TQ-2's bag-of-words stub and point the app at it.

    Must run before anything imports src.config, which reads OLLAMA_BASE_URL once.
    """
    from tests.utils.fake_ollama import FakeOllama

    stub = FakeOllama()
    os.environ["OLLAMA_BASE_URL"] = stub.start()
    return stub


def reranker_problem() -> str | None:
    """Why the reranker the configuration promises is not running, or None.

    The cross-encoder loads lazily and a load failure only logs a warning, after which
    retrieval proceeds without it. A gate that quietly lost the reranker would be scoring a
    pipeline that does not ship, so it refuses instead.
    """
    from src import config

    if not config.RERANKER_ENABLED:
        return None
    from src.rag.reranker import get_reranker

    if get_reranker().is_available():
        return None
    return ("RERANKER_ENABLED is true but the cross-encoder did not load, so this run would "
            "score retrieval without it. Fix the model download, or set "
            "RERANKER_ENABLED=false for the whole baseline, deliberately.")


def gate_record(result: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """What the baseline holds: the three metrics, and the settings that produced them."""
    return {
        "n": result["n"],
        "metrics": {m: round(result[m], 6) for m in GATE_METRICS},
        "settings": settings,
        "embedding": "tests/utils/fake_ollama.py (bag of words)",
    }


def compare_to_baseline(current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Every way *current* differs from *baseline*; empty means the gate passes.

    Exact, with no tolerance band: the stub is deterministic, so any movement came from
    the diff. A rise fails too — an unrecorded improvement leaves the baseline stale, and
    the next regression could then hide inside the gap.
    """
    problems = []
    if current["settings"] != baseline.get("settings"):
        problems.append(
            f"retrieval settings differ from the baseline's: {current['settings']} "
            f"vs {baseline.get('settings')} — a changed default is a new baseline, not a regression"
        )
    if current["n"] != baseline.get("n"):
        problems.append(f"{current['n']} cases, the baseline has {baseline.get('n')}")
    for metric in GATE_METRICS:
        now, then = current["metrics"][metric], baseline.get("metrics", {}).get(metric)
        if then is None or now == then:
            continue
        verb = "fell" if now < then else "rose"
        problems.append(f"{metric} {verb}: {then} -> {now}")
    return problems


REFUSAL = """
Query expansion adds no terms to any question, so an on/off comparison would
score identically and report +0.000 - which reads as "the feature does not
help" when it means "the feature never ran".

Two causes, in order of likelihood:

  1. The corpus was ingested with GRAPH_RAG_ENABLED off, so no entities exist.
     The flag governs extraction at ingest as well as expansion at query time.
     Re-run with it on and --ingest, and check spaCy's en_core_web_sm is
     installed: without it extraction is skipped silently and the ingest still
     reports success.

  2. The questions share no vocabulary with the indexed entities, which is what
     happens to natural-language questions over prose whose entities are
     codenames.

Refusing: a verdict on DEL-2 needs the feature to have actually run.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--corpus", type=Path, default=REPO_ROOT / "docs")
    parser.add_argument("--workspace-id", default=None)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--ingest", action="store_true",
                        help="ingest the corpus before scoring")
    parser.add_argument("--compare", choices=["graph", "reranker"],
                        help="score twice, with the feature off and on, and print the delta")
    parser.add_argument("--misses", action="store_true", help="list the questions that missed")
    parser.add_argument("--fake-ollama", action="store_true",
                        help="embed with the bag-of-words stub instead of a real model (EV-1)")
    gate = parser.add_mutually_exclusive_group()
    gate.add_argument("--check", action="store_true",
                      help="exit 1 if the score differs from --baseline in any way (EV-1)")
    gate.add_argument("--write-baseline", action="store_true",
                      help="record the score to --baseline instead of checking it")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args()

    if (args.check or args.write_baseline) and args.compare:
        parser.error("--check/--write-baseline score one configuration; drop --compare")

    stub = start_fake_ollama() if args.fake_ollama else None
    try:
        return _run(args)
    finally:
        if stub is not None:
            stub.stop()


def _run(args: argparse.Namespace) -> int:
    connect_db()

    cases = load_cases(args.cases)
    problems = verify_premises(cases, args.corpus)
    if problems:
        print("The eval set no longer describes the corpus:")
        for p in problems:
            print(f"  - {p}")
        print("\nFix the pairs before trusting a score; a rotted premise reads as a regression.")
        return 1
    print(f"{len(cases)} cases, premises verified against {args.corpus}")

    if args.ingest:
        print(f"\ningesting {args.corpus}...")
        print(f"  {ingest_corpus(args.corpus, args.workspace_id)} documents")

    from eval_answers import pin_retrieval_settings

    from src import config

    # Every path, not only the gate: retrieval prefers app_state.json's overrides to the
    # defaults, and a --compare run from a checkout whose settings page was used once
    # measured that checkout's TOP_K_RESULTS rather than the product's.
    settings = pin_retrieval_settings(config)
    print(f"  settings: {settings}")

    if args.check or args.write_baseline:
        return _gate(args, cases, settings)

    if not args.compare:
        report("current configuration", score(cases, args.top_k, args.workspace_id), args.misses)
        return 0

    # Both arms are read from config at call time, so flipping the module
    # attribute is what a deployment flipping the env var would do.
    flag = {"graph": "GRAPH_RAG_ENABLED", "reranker": "RERANKER_ENABLED"}[args.compare]

    # Refuse a comparison that cannot say anything. With no entities stored, the
    # "on" arm expands against nothing and ties with "off" — which reads as
    # "the feature does not help" when it in fact was never exercised.
    if args.compare == "graph":
        fired, total = graph_expansion_reach(cases)
        print(f"  expansion fires on {fired}/{total} questions")
        if fired == 0:
            print(REFUSAL)
            return 1

    original = getattr(config, flag)
    results = {}
    try:
        for state in (False, True):
            setattr(config, flag, state)
            results[state] = score(cases, args.top_k, args.workspace_id)
            report(f"{flag}={state}", results[state], args.misses)
    finally:
        setattr(config, flag, original)

    off, on = results[False], results[True]
    print(f"\n  delta with {flag} on:")
    for metric in ("recall@1", "recall@5", "mrr"):
        diff = on[metric] - off[metric]
        print(f"    {metric:9} {diff:+.3f}")
    print(
        "\n  DEL-2's rule: if the feature does not measurably lift grounding on our own\n"
        "  documents, it does not earn its place. One run is not a measurement — repeat\n"
        "  it before deciding, and record both numbers in PRODUCTION_PLAN.md."
    )
    return 0


def _gate(args: argparse.Namespace, cases: list[Case], settings: dict[str, Any]) -> int:
    problem = reranker_problem()
    if problem:
        print(f"\n{problem}")
        return 1

    result = score(cases, args.top_k, args.workspace_id)
    report("gate", result, show_misses=True)
    current = gate_record(result, settings)

    if args.write_baseline:
        args.baseline.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        print(f"\n  baseline written to {args.baseline}")
        return 0

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    problems = compare_to_baseline(current, baseline)
    if not problems:
        print("\n  matches the baseline")
        return 0
    print("\n  differs from the baseline:")
    for p in problems:
        print(f"    - {p}")
    print("\n  If this PR is meant to move retrieval, re-run with --write-baseline and commit\n"
          "  tests/eval/baseline.json in this diff. Never edit it to clear a red run.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
