"""PERF-1 — a slow retrieval must not stall every other request.

`api_chat` is `async def` but called sync `retrieve_contexts` (sync psycopg, a sync
httpx embedding call, cross-encoder inference) inline. On a single-threaded event
loop that holds the loop for the whole retrieval, so one slow query froze every
concurrent request — including SSE streams already mid-stream. The inference path
was made async long ago; retrieval never got the same treatment.

The test drives two requests concurrently against a retrieval that blocks for a
fixed time. Off the loop they overlap; on the loop they serialise. Timing is the
only thing that distinguishes the two, so timing is what this asserts — with a
margin wide enough that a slow machine cannot fail it, since the two outcomes
differ by a factor of two.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import httpx
import pytest

from tests.utils.auth import auth_headers, authenticated_state

BLOCK_SECONDS = 0.4

#: Serialised: 2 x BLOCK. Overlapped: ~1 x BLOCK. Anything under this only happens
#: when the blocking work actually left the event loop.
SERIALISED_FLOOR = BLOCK_SECONDS * 1.75


def _blocking_retrieve(*args, **kwargs):
    """Stands in for sync psycopg + embedding + reranking. Really blocks the thread."""
    time.sleep(BLOCK_SECONDS)
    return ("", "", [], None)


async def _fake_plan_and_memory(*args, **kwargs):
    return None, ""


async def _fake_stream(*args, **kwargs):
    yield "ok", "test-model"


def _app():
    from fastapi import FastAPI

    from src.routes_fastapi.api_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = authenticated_state()
    return app


async def _elapsed_for_two_concurrent_chats() -> float:
    app = _app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        started = time.perf_counter()
        responses = await asyncio.gather(*(
            client.post("/api/chat", json={"message": f"vraag {i}"}, headers=auth_headers())
            for i in range(2)
        ))
        elapsed = time.perf_counter() - started
    assert all(r.status_code == 200 for r in responses), [r.status_code for r in responses]
    return elapsed


@pytest.fixture
def chat_service():
    """Everything around retrieval stubbed, so only the blocking call sets the timing."""
    with patch("src.routes_fastapi.api_routes.chat") as svc, \
            patch("src.config.app_state") as app_state:
        app_state.get_active_model.return_value = "test-model"
        svc.parse_chat_request.side_effect = lambda data: {
            "message": data["message"], "use_rag": True, "enhance": False,
            "chat_history": [], "conversation_id": None, "images": None,
            "temperature": 0.7, "model_override": None,
            "additional_workspace_ids": None, "active_source_ids": None,
        }
        svc.retrieve_plan_and_memory = _fake_plan_and_memory
        svc.retrieve_contexts = _blocking_retrieve
        svc.apply_model_routing.return_value = ("test-model", None)
        svc.persist_user_message.return_value = ("conv-1", 1)
        svc.get_tool_executor.return_value = None
        svc.stream_chunks_with_fallback = _fake_stream
        svc.persist_assistant_message.return_value = 2
        yield svc


@pytest.mark.unit
class TestRetrievalRunsOffTheEventLoop:
    async def test_two_slow_chats_overlap_instead_of_queueing(self, chat_service):
        """The regression: inline on the loop this takes twice as long."""
        assert await _elapsed_for_two_concurrent_chats() < SERIALISED_FLOOR

    async def test_the_stand_in_really_blocks(self):
        """Guards the test itself: a no-op stand-in would pass no matter what."""
        started = time.perf_counter()
        await asyncio.get_running_loop().run_in_executor(None, _blocking_retrieve)
        assert time.perf_counter() - started >= BLOCK_SECONDS
