"""P2-3 — answer-level evaluation: does the chat answer correctly, faithfully, from the right source?

`eval_retrieval.py` scores whether the right *file* comes back for 20 questions about this
repository's docs. This scores what a user experiences, on a corpus of their own documents:

    draft      propose question / reference answer / verbatim proof triples from the corpus,
               written to a review file for a human to accept, fix or reject
    run        for every accepted case: retrieve as chat does, answer as chat does, and have
               a judge model grade the answer; writes per-case results and a summary
    rejudge    re-grade an existing run's answers under the cases as they stand now and the
               chosen judge prompt, without regenerating the answers
    calibrate  write a blind sheet of judged answers for a human to score, then report how
               often the judge agrees with the human (--score)
    check      compare a run's summary with the committed baseline; exit 1 on a regression,
               or --update the baseline from it

Metrics, over accepted cases:

    source_recall@1/@5, source_mrr  the case's source document among the retrieved documents,
                                    ranked by relevance (best chunk score), not by position
    proof_recall                    the verbatim proof passage is in the context the model saw
    citation_correct                the source document is among the sources the user is shown
    answer_correct                  judge: the answer matches the reference (yes 1, partial .5)
    faithfulness                    judge: every claim in the answer is supported by the context

The corpus is private, so everything this writes except the baseline's aggregate numbers
quotes it: `draft` and `run` refuse an output path inside the repository. Answers go through
the application's own path — `chat.get_rag_context`, `_build_context_prompt`, `OllamaClient` —
so the numbers describe the chat, not a reimplementation of it.

Needs the database and Ollama the application needs (PG_*, OLLAMA_BASE_URL). Not run in CI:
there is no model there, and the corpus is not in the repository.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import random
import re
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_BASELINE = REPO_ROOT / "tests" / "eval" / "answer_baseline.json"
GRADES = {"yes": 1.0, "partial": 0.5, "no": 0.0}
METRICS = (
    "source_recall@1", "source_recall@5", "source_mrr", "proof_recall",
    "citation_correct", "answer_correct", "faithfulness",
)


# ── pure helpers (unit-tested) ────────────────────────────────────────────────

def normalise(text: str) -> str:
    """Whitespace-collapsed, case-folded — how a proof is matched against a passage."""
    return re.sub(r"\s+", " ", text).strip().casefold()


def refuse_inside_repo(path: Path) -> None:
    """The outputs quote a private corpus; they must not be committable by accident."""
    resolved = path.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise SystemExit(
            f"refusing to write {path}: it is inside the repository, and this output quotes "
            "the corpus. Write it next to the corpus instead."
        )


def parse_json_object(raw: str) -> dict[str, Any] | None:
    """The first JSON object in a model reply, or None — models wrap JSON in prose."""
    start = raw.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(raw)):
            depth += {"{": 1, "}": -1}.get(raw[i], 0)
            if depth == 0:
                try:
                    value = json.loads(raw[start:i + 1])
                except json.JSONDecodeError:
                    break
                return value if isinstance(value, dict) else None
        start = raw.find("{", start + 1)
    return None


_TOC_LINE = re.compile(r"(\.{4,}|…{2,})\s*\d+\s*$|^\s*\d+(\.\d+)*\.?\s+\S.*\s\d{1,3}\s*$")
_TEMPLATE = re.compile(
    r"please (describe|provide|complete|fill in|specify)|\[insert|<insert|to be completed by"
    r"|\[bidder|\[supplier|\[tbd\]",
    re.IGNORECASE,
)


def looks_unusable(passage: str) -> bool:
    """A table of contents or a fill-in template: no fair question can be drafted from it.

    The first real draft took questions from both, and their "answers" were a section title or
    an invented value (P2-3 review). Boilerplate such as a disclaimer has no reliable pattern;
    the draft prompt lets the model skip that itself.
    """
    lines = [line for line in passage.splitlines() if line.strip()]
    toc_lines = sum(bool(_TOC_LINE.search(line)) for line in lines)
    return (len(lines) >= 4 and toc_lines / len(lines) >= 0.4) or bool(_TEMPLATE.search(passage))


def grade(value: Any) -> float | None:
    return GRADES.get(str(value).strip().lower())


def relevance_rank(source: str, scored: list[tuple[str, float]]) -> int | None:
    """1-based rank of the case's source among retrieved documents ordered by relevance.

    Each document scores as its best chunk. Not the order retrieval returns them in: that is
    alphabetical by file name (reading order, `_rank_and_finalize`), so ranking by position
    measured the alphabet — the first baseline's "source@1 = 0.14" did exactly that.
    """
    best: dict[str, float] = {}
    for name, score in scored:
        base = Path(name).name.casefold()
        best[base] = max(best.get(base, float("-inf")), score)
    order = sorted(best, key=lambda k: best[k], reverse=True)
    wanted = Path(source).name.casefold()
    return order.index(wanted) + 1 if wanted in order else None


def summarise(results: list[dict[str, Any]]) -> dict[str, float]:
    """Aggregate per-case results into the metrics above."""
    def mean(values: list[float]) -> float:
        return round(statistics.mean(values), 3) if values else 0.0

    ranks = [r["rank"] for r in results]
    return {
        "source_recall@1": mean([1.0 if k == 1 else 0.0 for k in ranks]),
        "source_recall@5": mean([1.0 if k is not None and k <= 5 else 0.0 for k in ranks]),
        "source_mrr": mean([1.0 / k if k else 0.0 for k in ranks]),
        "proof_recall": mean([1.0 if r["proof_in_context"] else 0.0 for r in results]),
        "citation_correct": mean([1.0 if r["rank"] is not None else 0.0 for r in results]),
        "answer_correct": mean([r["correct"] for r in results if r["correct"] is not None]),
        "faithfulness": mean([r["faithful"] for r in results if r["faithful"] is not None]),
    }


def regressions(summary: dict[str, float], baseline: dict[str, Any]) -> list[str]:
    """Metrics that fell more than the baseline's tolerance below it."""
    tolerance = float(baseline["tolerance"])
    return [
        f"{name}: {summary.get(name, 0.0):.3f} < {value:.3f} - {tolerance}"
        for name, value in baseline["metrics"].items()
        if summary.get(name, 0.0) < value - tolerance
    ]


def mean_bias(pairs: list[tuple[str, str]]) -> float | None:
    """Mean judge score minus mean human score over (human, judge) pairs: how far off, and which way.

    Agreement says how often the judge matches; bias says whether its misses lean one way —
    the number that tells a reader how much a judged metric is overstated.
    """
    scored = [(grade(h), grade(j)) for h, j in pairs if grade(h) is not None and grade(j) is not None]
    if not scored:
        return None
    return round(sum(j for _, j in scored) / len(scored) - sum(h for h, _ in scored) / len(scored), 3)


def instrument_mismatch(run_info: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """What differs between how a run and the baseline were measured.

    A v2-judged run against the v1 baseline reported answer_correct and faithfulness
    "regressions" that were only the judge becoming stricter.
    """
    return [
        f"{key} {run_info.get(key)!r} vs baseline {baseline.get(key)!r}"
        for key in ("answer_model", "judge_model", "judge_prompt", "retrieval")
        if run_info.get(key) != baseline.get(key)
    ]


def agreement(pairs: list[tuple[str, str]]) -> dict[str, float]:
    """Exact and within-one agreement on the yes/partial/no scale; the judge's reliability."""
    scored = [(grade(h), grade(j)) for h, j in pairs if grade(h) is not None and grade(j) is not None]
    if not scored:
        return {"n": 0, "exact": 0.0, "within_one": 0.0}
    return {
        "n": len(scored),
        "exact": round(sum(h == j for h, j in scored) / len(scored), 3),
        "within_one": round(sum(abs(h - j) <= 0.5 for h, j in scored) / len(scored), 3),
    }


def pin_retrieval_settings(config: Any) -> dict[str, Any]:
    """Drop the persisted RAG overrides for this process and return the settings in force.

    The settings page writes overrides to app_state.json in the working directory, and
    retrieval prefers them to the code's defaults. The first baseline was measured through a
    maintainer's local file (TOP_K_RESULTS 40, RERANK_TOP_K 10) that nobody else has — and a
    sweep of those settings by environment variable changed nothing. In memory only: the file
    is not touched.
    """
    config.app_state.state.pop("rag_params", None)
    keys = ("TOP_K_RESULTS", "RERANK_TOP_K", "DIVERSITY_THRESHOLD", "SEMANTIC_WEIGHT")
    settings = {k: config.app_state.get_rag_param(k) for k in keys}
    settings.update({
        k: getattr(config, k)
        for k in ("RERANKER_ENABLED", "RERANKER_WEIGHT", "CHUNK_SIZE", "CHUNK_OVERLAP", "MAX_CONTEXT_LENGTH")
    })
    return settings


# ── model calls ───────────────────────────────────────────────────────────────

def ask_json(model: str, prompt: str) -> dict[str, Any] | None:
    """One deterministic JSON-mode call to Ollama, for drafting and judging (not the answer)."""
    import httpx

    from src import config

    response = httpx.post(
        f"{config.OLLAMA_BASE_URL}/api/chat",
        json={
            "model": model, "stream": False, "format": "json",
            "options": {"temperature": 0},
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=300,
    )
    response.raise_for_status()
    return parse_json_object(response.json()["message"]["content"])


_DRAFT_PROMPT = """You are writing a test question for a document search assistant.

From the PASSAGE below, write ONE question that a colleague could ask and that this passage
answers specifically — not a generic question, and not one that needs other documents.
Also write a short reference answer (one to three sentences) using only the passage, and copy
a QUOTE of 5 to 25 consecutive words, exactly as written in the passage, that contains the
answer. Use the language of the passage.

The reference answer states only what the passage says: no inference about who benefits, what
follows from it, or a value the passage does not give. If the passage is a table of contents,
a blank template or instructions for filling one in, or generic boilerplate such as a
disclaimer, there is no fair question in it: reply {{"skip": true}}.

Reply with JSON only: {{"question": "...", "answer": "...", "quote": "..."}}

PASSAGE (from {source}):
{passage}"""

_JUDGE_HEAD = """You grade an assistant's answer.

QUESTION: {question}
REFERENCE ANSWER: {reference}
CONTEXT THE ASSISTANT WAS GIVEN:
{context}
ASSISTANT'S ANSWER:
{answer}

"""

# v1 checked the answer's main claim only. Reviewing its verdicts found the typical failure it
# passes: a correct core with an invented specific — a clause number, a section, a template
# name, who is responsible. v2 has every specific checked. Both stay selectable so the two can
# be compared on identical answers against the human calibration.
JUDGE_PROMPTS = {
    "v1": _JUDGE_HEAD + """Grade two things, each "yes", "partial" or "no":
- "correct": does the answer give the same information as the reference answer?
- "faithful": is every claim in the answer supported by the context? An answer that says the
  context does not contain the information is faithful if that is true.

Reply with JSON only: {{"correct": "...", "faithful": "...", "reason": "one sentence"}}""",
    "v2": _JUDGE_HEAD + """Grade two things, each "yes", "partial" or "no".

"correct": does the answer give the same information as the reference answer?
  "partial" if it gets the main point but misses or changes part of it.

"faithful": check EVERY specific detail in the answer against the context — numbers,
percentages, dates, clause, section and page numbers, document or template names, and who is
responsible for what.
  "yes" only if every detail appears in the context and means the same there;
  "partial" if the main claim is supported but at least one detail is not, or is changed;
  "no" if the main claim is not supported, or the answer misreads the context.
  An answer that says the context does not contain the information is faithful if that is true.

List the details you checked before deciding. Reply with JSON only:
{{"details_checked": ["..."], "unsupported": ["..."], "correct": "...", "faithful": "...",
"reason": "one sentence"}}""",
}


def judge(result: dict[str, Any], model: str, prompt: str) -> dict[str, Any]:
    """Grade one result's answer against its reference and the context it was given."""
    verdict = ask_json(model, JUDGE_PROMPTS[prompt].format(
        question=result["question"], reference=result["reference_answer"],
        context=result["context"], answer=result["answer"],
    )) or {}
    return {
        "correct": grade(verdict.get("correct")), "faithful": grade(verdict.get("faithful")),
        "judge_reason": verdict.get("reason"), "judge_unsupported": verdict.get("unsupported"),
    }


def select_for_rejudge(
    results: list[dict[str, Any]], cases: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[Any], list[Any]]:
    """Results to re-grade under the cases as they stand now, plus the ids dropped and stale.

    A rejected case is dropped. A case whose question changed is stale: its stored answer
    was to the old question, so it needs `run` again, not a new grade. A changed reference
    answer is taken from the case — that is what re-judging is for.
    """
    by_id = {c["id"]: c for c in cases}
    keep, dropped, stale = [], [], []
    for r in results:
        case = by_id.get(r["id"])
        if case is None or str(case.get("status")).lower() != "accepted":
            dropped.append(r["id"])
        elif normalise(case["question"]) != normalise(r["question"]):
            stale.append(r["id"])
        else:
            keep.append({**r, "reference_answer": case["reference_answer"]})
    return keep, dropped, stale


# ── subcommands ───────────────────────────────────────────────────────────────

def cmd_draft(args: argparse.Namespace) -> None:
    import yaml

    from src import config
    from src.rag.processor import doc_processor

    refuse_inside_repo(args.out)
    rng = random.Random(args.seed)
    files = sorted(
        p for p in args.corpus.rglob("*")
        if p.is_file() and p.suffix.lower() in config.SUPPORTED_EXTENSIONS
    )
    passages: list[tuple[Path, str]] = []
    for path in files:
        ok, _, chunks, *_ = doc_processor._load_document_chunks(
            str(path), path.name, path.suffix.lower(), None
        )
        usable = [
            c["text"] for c in (chunks or [])
            if 300 <= len(c["text"]) <= 2500 and not looks_unusable(c["text"])
        ] if ok else []
        rng.shuffle(usable)
        passages.extend((path, text) for text in usable[: args.per_file])
    rng.shuffle(passages)
    print(f"{len(files)} files, {len(passages)} candidate passages")

    cases: list[dict[str, Any]] = []
    for path, passage in passages:
        if len(cases) >= args.n:
            break
        reply = ask_json(args.model, _DRAFT_PROMPT.format(source=path.name, passage=passage))
        if not reply or reply.get("skip") or not all(reply.get(k) for k in ("question", "answer", "quote")):
            continue
        # The proof must be in the passage verbatim, or the case's premise is invented.
        if normalise(str(reply["quote"])) not in normalise(passage):
            continue
        cases.append({
            "id": len(cases) + 1,
            "status": "pending",
            "question": str(reply["question"]).strip(),
            "reference_answer": str(reply["answer"]).strip(),
            "source": str(path.relative_to(args.corpus)),
            "proof": str(reply["quote"]).strip(),
            # Whole, not an excerpt: the proof is often past the first few hundred characters,
            # and a reviewer has to see it to judge the case.
            "passage": passage,
        })
        print(f"  drafted {len(cases)}/{args.n}", end="\r")
    header = (
        "# Review every case: set status to accepted or rejected, and fix the question or\n"
        "# reference answer where needed. `passage` is there to review against; it is not scored.\n"
    )
    args.out.write_text(
        header + yaml.safe_dump({"cases": cases}, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    print(f"\n{len(cases)} cases written to {args.out}")


def _load_accepted(path: Path) -> list[dict[str, Any]]:
    import yaml

    cases = yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]
    accepted = [c for c in cases if str(c.get("status")).lower() == "accepted"]
    if not accepted:
        raise SystemExit(f"no case in {path} has status: accepted")
    return accepted


def cmd_run(args: argparse.Namespace) -> None:
    from src import config
    from src.db import db
    from src.ollama_client import OllamaClient
    from src.rag.processor import doc_processor
    from src.routes_fastapi.api_routes import _build_context_prompt
    from src.utils.scope import ALL_WORKSPACES

    refuse_inside_repo(args.out)
    settings = pin_retrieval_settings(config)
    cases = _load_accepted(args.cases)
    ok, message = db.initialize()
    if not ok:
        raise SystemExit(f"database unavailable: {message}")
    if args.ingest:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from eval_retrieval import ingest_corpus

        print(f"ingested {ingest_corpus(args.corpus, None)} documents")
    client = OllamaClient(base_url=config.OLLAMA_BASE_URL)
    # One loop for the whole run: the client's async HTTP pool is bound to the loop that first
    # used it, so an asyncio.run() per case failed on the second with "Event loop is closed".
    loop = asyncio.new_event_loop()

    results = []
    for n, case in enumerate(cases, 1):
        # What chat.get_rag_context does with MCP off, unrolled to keep each chunk's score.
        # The whole eval corpus, as before #406 made the scope a required argument —
        # this call was left without one, and `run` failed on its first case.
        retrieved = doc_processor.retrieve_context(case["question"], scope=ALL_WORKSPACES)
        context = doc_processor.format_context_for_llm(retrieved, max_length=config.MAX_CONTEXT_LENGTH)
        scored = [
            (r.filename, r.metadata["rerank_score"] if r.metadata.get("rerank_score") is not None
             else r.metadata.get("combined_score", r.similarity))
            for r in retrieved
        ]
        result = {
            "id": case["id"], "question": case["question"], "source": case["source"],
            "reference_answer": case["reference_answer"],
            # Exactly what the judge saw, so a human calibrating it can see the same.
            "context": context[:6000] or "(no documents were retrieved)",
            "rank": relevance_rank(case["source"], scored),
            "proof_in_context": normalise(case["proof"]) in normalise(context),
            "answer": None, "correct": None, "faithful": None,
        }
        if not args.retrieval_only:
            messages, final = _build_context_prompt(case["question"], context, "", [], True, False)
            messages.append({"role": "user", "content": final})
            reply = loop.run_until_complete(client.generate_chat_completion(args.model, messages))
            result["answer"] = reply["message"]["content"]
            result.update(judge(result, args.judge_model, args.judge_prompt))
        results.append(result)
        print(f"  {n}/{len(cases)}", end="\r")
    loop.close()
    summary = summarise(results)
    if args.retrieval_only:
        # No answers, no verdicts: the judged metrics would read 0.0, which is a claim, not a gap.
        summary = {k: v for k, v in summary.items() if k not in ("answer_correct", "faithfulness")}
    run_info = {
        "date": datetime.date.today().isoformat(), "cases": len(results),
        # A retrieval-only run names no models, so `check` will not compare it with the baseline.
        "answer_model": None if args.retrieval_only else args.model,
        "judge_model": None if args.retrieval_only else args.judge_model,
        "judge_prompt": None if args.retrieval_only else args.judge_prompt,
        "retrieval": settings,
    }
    args.out.write_text(
        json.dumps({"run": run_info, "summary": summary, "results": results}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("\n" + json.dumps({"run": run_info, "summary": summary}, indent=2))


def cmd_rejudge(args: argparse.Namespace) -> None:
    import yaml

    refuse_inside_repo(args.out)
    run = json.loads(args.results.read_text(encoding="utf-8"))
    cases = yaml.safe_load(args.cases.read_text(encoding="utf-8"))["cases"]
    keep, dropped, stale = select_for_rejudge(run["results"], cases)
    if dropped:
        print(f"dropped (no longer accepted): {dropped}")
    if stale:
        print(f"stale (question changed; needs `run`): {stale}")
    results = []
    for n, r in enumerate(keep, 1):
        results.append({**r, **judge(r, args.judge_model, args.judge_prompt)})
        print(f"  {n}/{len(keep)}", end="\r")
    summary = summarise(results)
    run_info = {
        **run["run"], "cases": len(results), "judge_model": args.judge_model,
        "judge_prompt": args.judge_prompt, "rejudged": datetime.date.today().isoformat(),
    }
    args.out.write_text(
        json.dumps({"run": run_info, "summary": summary, "results": results}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("\n" + json.dumps({"run": run_info, "summary": summary}, indent=2))


def cmd_calibrate(args: argparse.Namespace) -> None:
    import yaml

    results = json.loads(args.results.read_text(encoding="utf-8"))["results"]
    if args.score:
        data = yaml.safe_load(args.score.read_text(encoding="utf-8"))
        sheet = data["cases"]
        by_id = {r["id"]: r for r in results}
        inverse = {v: k for k, v in GRADES.items()}
        # A case rejected after grading has no result; say so rather than fail on it.
        scored = [c for c in sheet if c["id"] in by_id]
        # "correct" is graded against the reference answer shown on the sheet; where the case's
        # reference has since been fixed, the grade and the judge answer different questions.
        same_ref = [c for c in scored if c["reference_answer"] == by_id[c["id"]]["reference_answer"]]
        out: dict[str, Any] = {
            # The sheet says who graded it. Agreement with a model is not calibration against a
            # human, which is what P2-3 asks for; the grader travels with the number.
            "graders": sorted({str(c.get("grader", "human")) for c in scored}),
            "missing_results": [c["id"] for c in sheet if c["id"] not in by_id],
        }
        for dim in data.get("dims", ["correct", "faithful"]):
            rows = same_ref if dim == "correct" else scored
            pairs = [(c[f"human_{dim}"], inverse.get(by_id[c["id"]][dim], "")) for c in rows]
            out[dim] = {**agreement(pairs), "judge_bias": mean_bias(pairs)}
        print(json.dumps(out, indent=2))
        return
    refuse_inside_repo(args.out)
    dims = args.dims.split(",")
    sample = random.Random(args.seed).sample(results, min(args.n, len(results)))
    # Blind: the judge's verdicts are not on the sheet. JSON, so eval_review.html can score it.
    # Without "faithful" the context is left off: grading "correct" needs only the reference,
    # which is what makes a quick human pass (about ten seconds an answer) possible.
    sheet = [{
        "id": r["id"], "status": "pending", "question": r["question"],
        "reference_answer": r["reference_answer"], "answer": r["answer"],
        **({"context": r["context"]} if "faithful" in dims else {}),
        **{f"human_{d}": "" for d in dims},
    } for r in sample]
    args.out.write_text(json.dumps({
        "mode": "calibration", "dims": dims,
        "instructions": "Grade each answer yes, partial or no on: " + ", ".join(dims),
        "cases": sheet,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(sheet)} answers to grade on {', '.join(dims)} in {args.out}")


def cmd_check(args: argparse.Namespace) -> None:
    run = json.loads(args.results.read_text(encoding="utf-8"))
    if args.update:
        baseline = {
            "label": args.label, **run["run"], "tolerance": args.tolerance,
            "metrics": run["summary"],
            # How far the judge's numbers can be trusted, and against whom that was measured,
            # travel with them: a baseline read without its caveats overclaims.
            "calibration": json.loads(args.calibration.read_text(encoding="utf-8")) if args.calibration else None,
            "notes": args.note,
        }
        args.baseline.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
        print(f"baseline written to {args.baseline}")
        return
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    mismatch = instrument_mismatch(run["run"], baseline)
    if mismatch:
        raise SystemExit(
            "not comparable — the measuring instrument changed, not the chat: "
            + "; ".join(mismatch) + ". Re-baseline with --update if that change is intended."
        )
    failed = regressions(run["summary"], baseline)
    for line in failed:
        print(f"REGRESSION {line}")
    raise SystemExit(1 if failed else 0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)

    d = sub.add_parser("draft")
    d.add_argument("--corpus", type=Path, required=True)
    d.add_argument("--out", type=Path, required=True)
    d.add_argument("--n", type=int, default=120)
    d.add_argument("--per-file", type=int, default=3)
    d.add_argument("--model", default="mistral")
    d.add_argument("--seed", type=int, default=7)

    r = sub.add_parser("run")
    r.add_argument("--corpus", type=Path, required=True)
    r.add_argument("--cases", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--ingest", action="store_true")
    r.add_argument("--model", default="llama3.2")
    r.add_argument("--judge-model", default="mistral")
    r.add_argument("--judge-prompt", choices=sorted(JUDGE_PROMPTS), default="v2")
    r.add_argument("--retrieval-only", action="store_true",
                   help="retrieval metrics only: no answers, no judge; seconds, not an hour")

    j = sub.add_parser("rejudge")
    j.add_argument("--results", type=Path, required=True)
    j.add_argument("--cases", type=Path, required=True)
    j.add_argument("--out", type=Path, required=True)
    j.add_argument("--judge-model", default="mistral")
    j.add_argument("--judge-prompt", choices=sorted(JUDGE_PROMPTS), default="v2")

    c = sub.add_parser("calibrate")
    c.add_argument("--results", type=Path, required=True)
    c.add_argument("--out", type=Path)
    c.add_argument("--score", type=Path)
    c.add_argument("--n", type=int, default=20)
    c.add_argument("--seed", type=int, default=7)
    c.add_argument("--dims", default="correct,faithful",
                   help="what to grade; 'correct' alone makes a quick pass with no context to read")

    k = sub.add_parser("check")
    k.add_argument("--results", type=Path, required=True)
    k.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    k.add_argument("--update", action="store_true")
    k.add_argument("--label", default="private corpus")
    k.add_argument("--tolerance", type=float, default=0.05)
    k.add_argument("--calibration", type=Path, help="calibrate --score output to record with --update")
    k.add_argument("--note", action="append", default=[], help="a caveat to record with --update")

    args = ap.parse_args()
    {"draft": cmd_draft, "run": cmd_run, "rejudge": cmd_rejudge, "calibrate": cmd_calibrate,
     "check": cmd_check}[args.command](args)


if __name__ == "__main__":
    main()
