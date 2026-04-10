"""
Retrieval Feedback Pipeline
============================

Weekly job that exports feedback-labelled training pairs and optionally
fine-tunes a cross-encoder reranker on domain-specific relevance signals.

Running standalone (no Flask context needed)::

    python -m src.rag.feedback_pipeline --days 7 --output pairs.jsonl

Fine-tuning (requires sentence-transformers)::

    python -m src.rag.feedback_pipeline --finetune --model-dir ./models/reranker

The fine-tuning step is intentionally kept optional: if sentence-transformers
is not installed the pipeline exports pairs and exits cleanly.  The app runs
normally without this module — it is never imported at request time.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_training_pairs(db: Any, days: int = 7) -> list[dict]:
    """
    Pull (query, chunk_text, label) triples from the DB for the past *days* days.

    label=1 means the chunk was in a positively-rated answer.
    label=0 means the chunk was in a negatively-rated answer.
    """
    pairs = db.export_feedback_pairs(days=days)
    logger.info(f"[Pipeline] Exported {len(pairs)} training pairs (last {days} days)")
    return pairs


def write_jsonl(pairs: list[dict], path: str | Path) -> None:
    """Write training pairs to a JSON Lines file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for pair in pairs:
            fh.write(json.dumps(pair, ensure_ascii=False) + "\n")
    logger.info(f"[Pipeline] Wrote {len(pairs)} pairs to {path}")


# ---------------------------------------------------------------------------
# Evaluation helper
# ---------------------------------------------------------------------------

def _ndcg_at_k(labels: list[int], k: int = 10) -> float:
    """Compute NDCG@k for a single ranked list of binary relevance labels."""
    import math

    dcg = sum(
        rel / math.log2(rank + 2)
        for rank, rel in enumerate(labels[:k])
    )
    ideal = sorted(labels, reverse=True)
    idcg = sum(
        rel / math.log2(rank + 2)
        for rank, rel in enumerate(ideal[:k])
    )
    return dcg / idcg if idcg else 0.0


# ---------------------------------------------------------------------------
# Fine-tuning
# ---------------------------------------------------------------------------

def _versioned_output_dir(base_dir: str | Path) -> Path:
    """Return a timestamped subdirectory under *base_dir* for the new model version."""
    import time as _time
    ts = int(_time.time())
    versioned = Path(base_dir) / f"v{ts}"
    versioned.mkdir(parents=True, exist_ok=True)
    return versioned


def _write_latest_pointer(versioned_dir: Path) -> None:
    """Write a latest.txt file pointing at the versioned directory (Windows-safe)."""
    pointer = versioned_dir.parent / "latest.txt"
    pointer.write_text(str(versioned_dir), encoding="utf-8")


def persist_reranker_version(db: Any, result: dict) -> str | None:
    """Insert a reranker_versions row and return its UUID, or None on error."""
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO reranker_versions
                        (base_model, ndcg_before, ndcg_after, pair_count, model_path, active)
                    VALUES (%s, %s, %s, %s, %s, FALSE)
                    RETURNING id
                    """,
                    (
                        result.get("base_model", "cross-encoder/ms-marco-MiniLM-L-6-v2"),
                        result.get("ndcg_before"),
                        result.get("ndcg_after"),
                        result.get("pair_count"),
                        result.get("output_path"),
                    ),
                )
                return str(cur.fetchone()[0])
    except Exception as exc:
        logger.warning(f"[Pipeline] Could not persist reranker version: {exc}")
        return None


def promote_model(db: Any, version_id: str) -> bool:
    """Set *version_id* as active and update the latest.txt pointer. Returns success."""
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                # Fetch model path
                cur.execute("SELECT model_path FROM reranker_versions WHERE id = %s", (version_id,))
                row = cur.fetchone()
                if not row:
                    return False
                model_path = row[0]
                # Demote all, promote this one
                cur.execute("UPDATE reranker_versions SET active = FALSE")
                cur.execute(
                    "UPDATE reranker_versions SET active = TRUE WHERE id = %s", (version_id,)
                )
        # Update latest.txt
        if model_path:
            pointer = Path(model_path).parent / "latest.txt"
            pointer.parent.mkdir(parents=True, exist_ok=True)
            pointer.write_text(model_path, encoding="utf-8")
        from ..rag.reranker import reload_reranker
        reload_reranker(model_path)
        logger.info(f"[Pipeline] Promoted reranker version {version_id} ({model_path})")
        return True
    except Exception as exc:
        logger.warning(f"[Pipeline] Promote failed: {exc}")
        return False


def rollback_model(db: Any, version_id: str) -> bool:
    """Alias for promote_model — re-promotes any previously-trained version."""
    return promote_model(db, version_id)


def finetune_reranker(
    pairs: list[dict],
    base_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    output_dir: str | Path = "./models/reranker",
    epochs: int = 3,
    batch_size: int = 16,
) -> dict[str, Any]:
    """
    Fine-tune a cross-encoder reranker on domain feedback pairs.

    Requires:  pip install sentence-transformers>=3.0

    Args:
        pairs:       List of {query, chunk_text, label} dicts.
        base_model:  Hugging Face model ID to start from.
        output_dir:  Where to save the fine-tuned model.
        epochs:      Training epochs.
        batch_size:  Training batch size.

    Returns:
        Dict with {ndcg_before, ndcg_after, output_path, pair_count}.
    """
    try:
        from sentence_transformers import CrossEncoder
        from sentence_transformers.cross_encoder.evaluation import CERerankingEvaluator
    except ImportError as exc:
        logger.warning(
            "[Pipeline] sentence-transformers not installed — skipping fine-tune. "
            "Install with: pip install 'sentence-transformers>=3.0'"
        )
        raise RuntimeError("sentence-transformers not available") from exc

    if not pairs:
        logger.info("[Pipeline] No training pairs — skipping fine-tune")
        return {"pair_count": 0, "skipped": True}

    # Use a versioned subdirectory so previous models are preserved
    versioned_dir = _versioned_output_dir(output_dir)

    # Build sentence-transformers InputExample format
    from sentence_transformers import InputExample

    train_samples = [
        InputExample(texts=[p["query"], p["chunk_text"]], label=float(p["label"]))
        for p in pairs
        if p.get("query") and p.get("chunk_text") and p.get("label") in (0, 1)
    ]

    if not train_samples:
        logger.warning("[Pipeline] No valid training samples after filtering")
        return {"pair_count": 0, "skipped": True}

    # Split 80/20 for eval
    split = int(len(train_samples) * 0.8)
    train_set, eval_set = train_samples[:split], train_samples[split:]

    model = CrossEncoder(base_model, num_labels=1)

    # Baseline NDCG on eval set (before fine-tuning)
    eval_labels = [int(s.label) for s in eval_set]
    ndcg_before = _ndcg_at_k(eval_labels)

    model.fit(
        train_dataloader=train_set,
        epochs=epochs,
        batch_size=batch_size,
        warmup_steps=max(10, len(train_samples) // 10),
        output_path=str(versioned_dir),
        show_progress_bar=False,
    )

    # Post-fine-tune NDCG
    scores = model.predict([(s.texts[0], s.texts[1]) for s in eval_set])
    ranked = [label for _, label in sorted(zip(scores, eval_labels), reverse=True)]
    ndcg_after = _ndcg_at_k(ranked)

    _write_latest_pointer(versioned_dir)

    logger.info(
        f"[Pipeline] Fine-tune complete: NDCG@10 {ndcg_before:.3f} → {ndcg_after:.3f}  "
        f"pairs={len(train_samples)}  output={versioned_dir}"
    )
    return {
        "base_model": base_model,
        "pair_count": len(train_samples),
        "ndcg_before": round(ndcg_before, 4),
        "ndcg_after": round(ndcg_after, 4),
        "output_path": str(versioned_dir),
        "skipped": False,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run(db: Any, days: int = 7, output: str | Path | None = None, finetune: bool = False, **kwargs) -> dict:
    """
    Full pipeline run.  Safe to call from a cron job or management command.

    Returns a summary dict suitable for logging / dashboard display.
    """
    pairs = export_training_pairs(db, days=days)

    if output:
        write_jsonl(pairs, output)

    result: dict[str, Any] = {
        "pairs_exported": len(pairs),
        "days": days,
    }

    if finetune and pairs:
        try:
            ft_result = finetune_reranker(pairs, **kwargs)
            result["finetune"] = ft_result
        except RuntimeError as exc:
            result["finetune"] = {"error": str(exc)}

    return result


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="LocalChat Retrieval Feedback Pipeline")
    parser.add_argument("--days", type=int, default=7, help="Days of feedback to export")
    parser.add_argument("--output", type=str, default=None, help="JSONL output path")
    parser.add_argument("--finetune", action="store_true", help="Run reranker fine-tuning")
    parser.add_argument("--model-dir", type=str, default="./models/reranker", help="Output dir for fine-tuned model")
    args = parser.parse_args()

    from src.db import db as _db

    summary = run(_db, days=args.days, output=args.output, finetune=args.finetune, output_dir=args.model_dir)
    print(json.dumps(summary, indent=2))
