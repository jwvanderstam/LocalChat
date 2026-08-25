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

Needs a database and an embedding model — the same services the app needs. It
is not wired into CI: with a stubbed model the numbers measure the stub, and
the whole point is to measure the real retrieval stack. Run it before and after
a change to the RAG path, an embedding model, or the reranker, and record both.

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
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CASES = REPO_ROOT / "tests" / "eval" / "retrieval_cases.yaml"


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


def verify_premises(cases: list[Case]) -> list[str]:
    """Check every case still describes the corpus.

    A pair whose source was rewritten stops being a retrieval question and
    becomes an unanswerable one — and it drags the score down silently, which
    reads as a regression in the retriever rather than rot in the fixture.
    """
    problems = []
    for case in cases:
        path = REPO_ROOT / case.source
        if not path.exists():
            problems.append(f"{case.source}: file is gone")
            continue
        if case.proof not in path.read_text(encoding="utf-8", errors="replace"):
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
    from src.rag.processor import doc_processor

    count = 0
    for path in sorted(corpus.glob("*.md")):
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
    from src.rag.processor import doc_processor

    hits_at_1 = 0
    hits_at_5 = 0
    reciprocal = 0.0
    misses: list[tuple[str, str]] = []

    for case in cases:
        results = doc_processor.retrieve_context(
            case.question, top_k=top_k, workspace_id=workspace_id
        )
        # Chunks collapse to the file they came from, in rank order, first win.
        ranked: list[str] = []
        for r in results:
            name = Path(r.filename).name
            if name not in ranked:
                ranked.append(name)

        want = Path(case.source).name
        if want in ranked:
            rank = ranked.index(want) + 1
            reciprocal += 1.0 / rank
            if rank == 1:
                hits_at_1 += 1
            if rank <= 5:
                hits_at_5 += 1
        else:
            misses.append((case.question, ranked[0] if ranked else "(nothing)"))

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
    args = parser.parse_args()

    connect_db()

    cases = load_cases(args.cases)
    problems = verify_premises(cases)
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

    if not args.compare:
        report("current configuration", score(cases, args.top_k, args.workspace_id), args.misses)
        return 0

    # Both arms are read from config at call time, so flipping the module
    # attribute is what a deployment flipping the env var would do.
    from src import config

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


if __name__ == "__main__":
    raise SystemExit(main())
