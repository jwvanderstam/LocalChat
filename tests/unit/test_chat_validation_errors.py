"""A rejected field must answer 422 with a readable reason, not 500.

Found while wiring an n8n bridge to `/api/chat`: sending `conversation_id: ""`
answered ``500 An unexpected error occurred``. Validation was working — it raised
422 — but building that response called ``exc.errors()``, whose ``ctx`` holds the
originating ``ValueError`` object. ``JSONResponse`` cannot serialise it, so a
``TypeError`` escaped the handler and became a generic 500.

That hid every validation message on the endpoint, and pointed the caller at the
server when the fix was in their request. The empty id itself is now read as "no
conversation yet", which is what a client that always sends the field means.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.models import ChatRequest
from src.routes_fastapi.api_routes import router
from tests.utils.auth import auth_headers, authenticated_state

VALID_ID = str(uuid.uuid4())


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = authenticated_state()
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update(auth_headers())
    return client


@pytest.mark.unit
class TestValidationAnswers422:
    """The reported bug. Each of these previously answered 500."""

    def test_a_bad_conversation_id_is_a_client_error_not_a_server_error(self, client):
        resp = client.post("/api/chat", json={"message": "hoi", "conversation_id": "null"})
        assert resp.status_code == 422

    def test_an_empty_message_is_a_client_error_not_a_server_error(self, client):
        """Not conversation_id-specific: any validator raising ValueError hit this."""
        resp = client.post("/api/chat", json={"message": "   "})
        assert resp.status_code == 422

    def test_the_response_names_the_offending_field(self, client):
        """A 422 whose details were dropped would still leave the caller guessing."""
        resp = client.post("/api/chat", json={"message": "hoi", "conversation_id": "null"})
        assert "conversation_id" in json.dumps(resp.json()["details"])

    def test_the_response_body_is_serialisable(self, client):
        """The defect itself: the payload could not be rendered, so it never arrived."""
        resp = client.post("/api/chat", json={"message": "hoi", "conversation_id": "null"})
        json.dumps(resp.json())


@pytest.mark.unit
class TestEmptyConversationIdMeansNewConversation:
    def test_empty_string_is_read_as_absent(self):
        assert ChatRequest(message="hoi", conversation_id="").conversation_id is None

    def test_whitespace_is_read_as_absent(self):
        assert ChatRequest(message="hoi", conversation_id="   ").conversation_id is None

    def test_an_omitted_id_is_still_none(self):
        assert ChatRequest(message="hoi").conversation_id is None


@pytest.mark.unit
class TestARealIdIsStillRequiredToBeReal:
    """The negative space: "empty means new" must not become "anything means new"."""

    def test_a_valid_uuid_is_kept_unchanged(self):
        assert ChatRequest(message="hoi", conversation_id=VALID_ID).conversation_id == VALID_ID

    def test_the_literal_string_null_is_still_rejected(self):
        """A client sending "null" has a bug; silently starting a new conversation
        would lose the thread every turn and look like the model forgetting."""
        with pytest.raises(ValidationError):
            ChatRequest(message="hoi", conversation_id="null")

    def test_a_malformed_uuid_is_still_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="hoi", conversation_id="not-a-uuid")
