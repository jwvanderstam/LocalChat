"""MemoriesService — the scope on every call, who retired what, and batch extraction.

QP-4, aggregate 5. The route's guard decides whether the caller may act; these prove the
service passes the authorised scope through, and that one failed conversation does not
abandon the rest of an extraction batch.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.memories import MemoriesService

pytestmark = pytest.mark.unit

USER = "33333333-3333-3333-3333-333333333333"
SCOPE = "11111111-1111-1111-1111-111111111111"


def _service() -> tuple[MemoriesService, MagicMock]:
    db = MagicMock()
    return MemoriesService(db), db


class TestTheScopeReachesTheRepository:
    def test_list_page(self):
        service, db = _service()
        db.memories.list_page.return_value = [{"id": "m1"}]
        assert service.list_page(100, 0, SCOPE) == [{"id": "m1"}]
        db.memories.list_page.assert_called_once_with(limit=100, offset=0, scope=SCOPE)

    def test_retire_records_the_caller(self):
        service, db = _service()
        db.memories.retire.return_value = True
        assert service.retire("m1", USER, SCOPE) is True
        db.memories.retire.assert_called_once_with("m1", deleted_by=USER, scope=SCOPE)

    @pytest.mark.parametrize("caller", [None, "", "anonymous"])
    def test_retire_all_records_nobody_without_a_caller(self, caller):
        service, db = _service()
        db.memories.retire_all.return_value = 2
        assert service.retire_all(caller, SCOPE) == 2
        db.memories.retire_all.assert_called_once_with(deleted_by=None, scope=SCOPE)


class TestExtract:
    async def test_counts_two_conversations_and_reads_them_in_the_scope(self):
        service, db = _service()
        db.memories.unextracted_conversations.return_value = [
            {"id": "c1", "workspace_id": SCOPE},
            {"id": "c2", "workspace_id": SCOPE},
        ]
        db.conversations.messages.return_value = [{"role": "user", "content": "I like tea"}]
        extractor = MagicMock()
        extractor.extract = AsyncMock(side_effect=[2, 3])
        with patch("src.memory.extractor.MemoryExtractor", return_value=extractor):
            counts = await service.extract(10, SCOPE, "model", ollama_client=MagicMock())
        assert counts == {"conversations_processed": 2, "new_memories": 5}
        db.memories.unextracted_conversations.assert_called_once_with(limit=10, scope=SCOPE)
        assert [c.kwargs["scope"] for c in db.conversations.messages.call_args_list] == [SCOPE, SCOPE]
        assert extractor.extract.call_args_list[0].kwargs["messages"] == [
            {"role": "user", "content": "I like tea"}
        ]

    async def test_one_failure_does_not_abandon_the_batch(self):
        service, db = _service()
        db.memories.unextracted_conversations.return_value = [{"id": "c1"}, {"id": "c2"}]
        db.conversations.messages.return_value = []
        extractor = MagicMock()
        extractor.extract = AsyncMock(side_effect=[RuntimeError("model down"), 4])
        with patch("src.memory.extractor.MemoryExtractor", return_value=extractor):
            counts = await service.extract(10, SCOPE, "model", ollama_client=MagicMock())
        assert counts == {"conversations_processed": 1, "new_memories": 4}

    async def test_a_conversation_retired_meanwhile_is_skipped_not_processed(self):
        service, db = _service()
        db.memories.unextracted_conversations.return_value = [{"id": "gone"}]
        db.conversations.messages.return_value = None
        extractor = MagicMock()
        extractor.extract = AsyncMock(return_value=1)
        with patch("src.memory.extractor.MemoryExtractor", return_value=extractor):
            counts = await service.extract(10, SCOPE, "model", ollama_client=MagicMock())
        assert counts == {"conversations_processed": 0, "new_memories": 0}
        extractor.extract.assert_not_called()

    async def test_each_message_shape_reaches_the_extractor_as_role_and_content(self):
        service, db = _service()
        db.memories.unextracted_conversations.return_value = [{"id": "c1", "workspace_id": SCOPE}]
        db.conversations.messages.return_value = [
            {},
            ("user", "I like tea"),
            ("assistant", "Noted", "2026-10-25"),
            ("orphan",),
            "xy",
        ]
        extractor = MagicMock()
        extractor.extract = AsyncMock(return_value=0)
        with patch("src.memory.extractor.MemoryExtractor", return_value=extractor):
            await service.extract(10, SCOPE, "model", ollama_client=MagicMock())
        kwargs = extractor.extract.call_args.kwargs
        assert kwargs["messages"] == [
            {"role": "", "content": ""},
            {"role": "user", "content": "I like tea"},
            {"role": "assistant", "content": "Noted"},
        ]
        assert kwargs["workspace_id"] == SCOPE
