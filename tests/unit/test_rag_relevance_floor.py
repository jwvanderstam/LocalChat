"""T1 — an arithmetic question came back citing a Dutch IT tender document.

Measured against the running instance: "hoeveel is 8+7" scored **0.61** embedding
similarity against that document, against a threshold of 0.30. No threshold
separates those without discarding real matches — a short query's cosine score is
dominated by language and domain rather than content, so 0.61 means nothing in
absolute terms.

The cross-encoder scored the same passages **-11.40, -11.44 and +0.81**. It knew.
Reranking only ever *reordered*, so its verdict changed the order of the irrelevant
chunks and returned them anyway. The model then said the documents contained no
answer and cited them in the same breath.
"""

from __future__ import annotations

import pytest

from src import config
from src.rag.retrieval import RetrievalMixin

pytestmark = pytest.mark.unit


def _chunk(name: str, rerank: float | None, *, score: float = 0.6) -> dict:
    return {
        "chunk_text": f"text of {name}",
        "filename": f"{name}.pdf",
        "chunk_index": 0,
        "semantic_score": score,
        "combined_score": score,
        "rerank_score": rerank,
        "chunk_id": 1,
        "metadata": {},
    }


@pytest.fixture
def retriever():
    return RetrievalMixin()


@pytest.fixture(autouse=True)
def _pinned_thresholds(monkeypatch):
    """Pin the documented values rather than reading whatever config holds.

    A test that references the constant moves with it when the constant is
    mutated, which is exactly the trap the mutation work recorded.
    """
    monkeypatch.setattr(config, "RERANK_MIN_SCORE", -5.0)
    monkeypatch.setattr(config, "RERANK_LOW_RELEVANCE_LIMIT", 3)


class TestDroppingTheIrrelevant:
    def test_a_chunk_the_cross_encoder_rejects_is_dropped(self, retriever):
        """The reported case: -11.4 alongside a genuine +0.81."""
        kept = retriever._apply_relevance_floor([
            _chunk("tender", -11.40),
            _chunk("arithmetic", 0.81),
        ])
        assert [c["filename"] for c in kept] == ["arithmetic.pdf"]

    def test_a_chunk_just_above_the_floor_is_kept(self, retriever):
        """The floor sits well below zero so only the plainly irrelevant goes."""
        kept = retriever._apply_relevance_floor([_chunk("borderline", -4.9)])
        assert len(kept) == 1

    def test_a_chunk_exactly_on_the_floor_is_kept(self, retriever):
        """Inclusive, and asserted so the comparison cannot drift to exclusive."""
        kept = retriever._apply_relevance_floor([_chunk("exact", -5.0)])
        assert len(kept) == 1

    def test_a_chunk_just_below_the_floor_is_dropped(self, retriever):
        kept = retriever._apply_relevance_floor([
            _chunk("below", -5.001),
            _chunk("good", 1.0),
        ])
        assert [c["filename"] for c in kept] == ["good.pdf"]

    def test_nothing_is_marked_low_relevance_when_something_clears(self, retriever):
        kept = retriever._apply_relevance_floor([_chunk("good", 1.0)])
        assert not kept[0].get("low_relevance")


class TestWhenNothingClears:
    """The decision: show the best few, marked, rather than nothing at all."""

    def test_the_best_few_are_still_returned(self, retriever):
        kept = retriever._apply_relevance_floor([
            _chunk("a", -11.0), _chunk("b", -9.0), _chunk("c", -10.0), _chunk("d", -12.0),
        ])
        assert len(kept) == 3

    def test_they_are_the_best_ones(self, retriever):
        kept = retriever._apply_relevance_floor([
            _chunk("worst", -12.0), _chunk("best", -8.0), _chunk("middle", -10.0),
        ])
        assert kept[0]["filename"] == "best.pdf"

    def test_they_are_marked_low_relevance(self, retriever):
        """The mark is the whole point — an unmarked weak source is the bug."""
        kept = retriever._apply_relevance_floor([_chunk("a", -11.0)])
        assert all(c["low_relevance"] for c in kept)

    def test_at_least_one_is_kept_even_if_the_limit_is_zero(self, retriever, monkeypatch):
        """A misconfigured limit must not silently turn this into "return nothing"."""
        monkeypatch.setattr(config, "RERANK_LOW_RELEVANCE_LIMIT", 0)
        assert len(retriever._apply_relevance_floor([_chunk("a", -11.0)])) == 1


class TestWithoutTheCrossEncoder:
    """The reranker is optional; the floor cannot become a silent filter without it."""

    def test_unscored_chunks_pass_through_untouched(self, retriever):
        chunks = [_chunk("a", None), _chunk("b", None)]
        assert retriever._apply_relevance_floor(chunks) == chunks

    def test_an_empty_result_stays_empty(self, retriever):
        assert retriever._apply_relevance_floor([]) == []
