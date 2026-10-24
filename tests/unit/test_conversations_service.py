"""ConversationsService — paging, the scope on every call, and who retired what.

QP-4, aggregate 4. The route's guard decides whether the caller may act; these prove
the service passes the authorised scope through unchanged and computes ``has_more``
from the page it actually got.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.services.conversations import ConversationsService

pytestmark = pytest.mark.unit

USER = "33333333-3333-3333-3333-333333333333"
SCOPE = "11111111-1111-1111-1111-111111111111"
CONV = "22222222-2222-2222-2222-222222222222"


def _service() -> tuple[ConversationsService, MagicMock]:
    db = MagicMock()
    return ConversationsService(db), db


class TestPage:
    def test_a_full_page_with_more_behind_it(self):
        service, db = _service()
        db.conversations.list_page.return_value = [{"id": "a"}, {"id": "b"}]
        db.conversations.count.return_value = 5
        assert service.page(2, 0, SCOPE) == {
            "conversations": [{"id": "a"}, {"id": "b"}],
            "limit": 2,
            "offset": 0,
            "total": 5,
            "has_more": True,
        }

    def test_the_last_page_has_no_more(self):
        service, db = _service()
        db.conversations.list_page.return_value = [{"id": "e"}]
        db.conversations.count.return_value = 5
        assert service.page(2, 4, SCOPE)["has_more"] is False

    def test_the_listing_and_the_count_use_the_same_scope(self):
        service, db = _service()
        db.conversations.list_page.return_value = []
        db.conversations.count.return_value = 0
        service.page(50, 10, SCOPE)
        db.conversations.list_page.assert_called_once_with(limit=50, offset=10, scope=SCOPE)
        db.conversations.count.assert_called_once_with(scope=SCOPE)


class TestTheScopeReachesTheRepository:
    def test_messages(self):
        service, db = _service()
        db.conversations.messages.return_value = None
        assert service.messages(CONV, SCOPE) is None
        db.conversations.messages.assert_called_once_with(CONV, scope=SCOPE)

    def test_document_filter(self):
        service, db = _service()
        service.set_document_filter(CONV, ["a.pdf"], SCOPE)
        db.conversations.set_document_filter.assert_called_once_with(CONV, ["a.pdf"], scope=SCOPE)

    def test_set_title(self):
        service, db = _service()
        service.set_title(CONV, "New", SCOPE)
        db.conversations.set_title.assert_called_once_with(CONV, "New", scope=SCOPE)


class TestRetirementRecordsTheCaller:
    def test_retire_one(self):
        service, db = _service()
        db.conversations.retire.return_value = True
        assert service.retire(CONV, USER, SCOPE) is True
        db.conversations.retire.assert_called_once_with(CONV, deleted_by=USER, scope=SCOPE)

    def test_retire_all(self):
        service, db = _service()
        db.conversations.retire_all.return_value = 3
        assert service.retire_all(USER, SCOPE) == 3
        db.conversations.retire_all.assert_called_once_with(deleted_by=USER, scope=SCOPE)

    @pytest.mark.parametrize("caller", [None, "", "anonymous"])
    def test_no_caller_records_nobody(self, caller):
        service, db = _service()
        service.retire_all(caller, SCOPE)
        db.conversations.retire_all.assert_called_once_with(deleted_by=None, scope=SCOPE)
