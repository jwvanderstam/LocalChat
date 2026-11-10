"""DocumentsService — the scope reaches every query, and an unavailable database is a 503.

QP-4, aggregate 3. The route's guard decides whether the caller may act; these prove
the service hands the authorised scope to the repository unchanged, records who retired
what, and turns ``DatabaseUnavailableError`` into a refusal the route can send.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.db.connection import DatabaseUnavailableError
from src.services.documents import DocumentsService
from src.services.errors import ServiceError

pytestmark = pytest.mark.unit

USER = "33333333-3333-3333-3333-333333333333"
SCOPE = "11111111-1111-1111-1111-111111111111"


def _service() -> tuple[DocumentsService, MagicMock]:
    db = MagicMock()
    return DocumentsService(db), db


class TestTheScopeReachesTheRepository:
    def test_list(self):
        service, db = _service()
        db.documents.list_all.return_value = [{"id": 1}]
        assert service.list_all(SCOPE) == [{"id": 1}]
        db.documents.list_all.assert_called_once_with(scope=SCOPE)

    def test_stats_counts_documents_and_chunks_in_the_scope(self):
        service, db = _service()
        db.documents.count.return_value = 3
        db.documents.chunk_count.return_value = 40
        db.documents.chunk_statistics.return_value = {"avg": 1}
        assert service.stats(SCOPE) == {
            "document_count": 3,
            "chunk_count": 40,
            "chunk_statistics": {"avg": 1},
        }
        db.documents.count.assert_called_once_with(scope=SCOPE)
        db.documents.chunk_count.assert_called_once_with(scope=SCOPE)
        db.documents.chunk_statistics.assert_called_once_with(scope=SCOPE)

    def test_search_text(self):
        service, db = _service()
        service.search_text("needle", 5, SCOPE)
        db.documents.search_text.assert_called_once_with("needle", 5, scope=SCOPE)


class TestChunkContext:
    def test_neighbours_are_read_in_the_same_scope_as_the_chunk(self):
        service, db = _service()
        db.documents.chunk_by_id.return_value = {"document_id": 7, "chunk_index": 4}
        db.documents.adjacent_chunks.return_value = [("a", 3), ("b", 4), ("c", 5)]
        context = service.chunk_context(99, 1, SCOPE)
        assert context == {
            "document_id": 7,
            "chunk_index": 4,
            "chunks": [
                {"chunk_text": "a", "chunk_index": 3},
                {"chunk_text": "b", "chunk_index": 4},
                {"chunk_text": "c", "chunk_index": 5},
            ],
        }
        db.documents.chunk_by_id.assert_called_once_with(99, scope=SCOPE)
        db.documents.adjacent_chunks.assert_called_once_with(7, 4, window_size=1, scope=SCOPE)

    def test_a_chunk_outside_the_scope_is_none_and_reads_no_neighbours(self):
        service, db = _service()
        db.documents.chunk_by_id.return_value = None
        assert service.chunk_context(99, 1, SCOPE) is None
        db.documents.adjacent_chunks.assert_not_called()


class TestRetirementRecordsTheCaller:
    def test_retire_one(self):
        service, db = _service()
        db.documents.retire.return_value = True
        assert service.retire(5, USER, SCOPE) is True
        db.documents.retire.assert_called_once_with(5, USER, scope=SCOPE)

    def test_retire_all(self):
        service, db = _service()
        db.documents.retire_all.return_value = 4
        assert service.retire_all(USER, SCOPE) == 4
        db.documents.retire_all.assert_called_once_with(scope=SCOPE, deleted_by=USER)

    @pytest.mark.parametrize("caller", [None, "", "anonymous"])
    def test_no_caller_records_nobody(self, caller):
        service, db = _service()
        service.retire(5, caller, SCOPE)
        db.documents.retire.assert_called_once_with(5, None, scope=SCOPE)


class TestAnUnavailableDatabaseIsA503:
    @pytest.mark.parametrize(
        ("method", "call"),
        [
            ("list_all", lambda s: s.list_all(SCOPE)),
            ("count", lambda s: s.stats(SCOPE)),
            ("retire", lambda s: s.retire(1, USER, SCOPE)),
            ("retire_all", lambda s: s.retire_all(USER, SCOPE)),
            ("purge", lambda s: s.purge(1)),
            ("purge_all", lambda s: s.purge_all()),
        ],
    )
    def test_refused_with_503(self, method, call):
        service, db = _service()
        getattr(db.documents, method).side_effect = DatabaseUnavailableError("down")
        with pytest.raises(ServiceError) as refused:
            call(service)
        assert (refused.value.status_code, refused.value.message) == (503, "Database unavailable")

    def test_any_other_error_is_not_turned_into_a_refusal(self):
        service, db = _service()
        db.documents.purge.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError):
            service.purge(1)
