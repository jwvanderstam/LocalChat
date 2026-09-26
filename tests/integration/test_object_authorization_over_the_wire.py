"""P2-2b — every object route refuses a foreign workspace's object, over HTTP.

`tests/unit/test_object_authorization_matrix.py` proves the *property* by walking the
AST: no call to a workspace-scoped database method may omit ``scope=``. That is what
catches a new route, and it is cheap. What it cannot do is prove the scope that arrives
at the database is the one the guard authorised, through a real request, against real
rows — the audit's C1 and C2 were reproduced over HTTP, and nothing in CI reproduces
them the same way. Every workspace test in `tests/integration/` is `MagicMock`
throughout.

So this drives the real thing: a plain user, signed in over HTTP, holding workspace A,
addressing objects that live in workspace B. Every such request must be refused.

**The route list is derived, not written down.** It comes from `app.openapi()`, which is
what the application actually serves, so a route added tomorrow is covered tomorrow.
`app.routes` is not usable for this — this FastAPI version wraps included routers in
`_IncludedRouter` objects whose `path` is `None`, so a naive walk finds nothing and the
suite would pass by testing zero routes.

**An unclassified path parameter is a failure, not a skip.** `_PARAM_KIND` below maps
every parameter name the application serves to how it must be treated. A new parameter
nobody classified fails `test_every_path_parameter_is_classified` with instructions,
rather than silently dropping its routes out of the matrix — which is how a derived test
quietly stops testing anything.

**Why the fixture asserts its own objects are reachable.** A 404 is a passing result
here, so a fixture that failed to create anything would produce a perfect green run with
no authorization exercised at all — the tautological case `.claude/rules/testing.md`
names. `test_the_fixture_objects_are_reachable_by_their_owner` is the guard: the owner
must get a non-404 for each provisioned object before any refusal means anything.
"""

from __future__ import annotations

import os
import re
import uuid
from typing import Any

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.slow]

httpx = pytest.importorskip("httpx", reason="the matrix is driven over HTTP")

from tests.e2e.conftest import (  # noqa: E402,F401
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    live_server,
)

_PARAM_RE = re.compile(r"\{(\w+)\}")

#: How each path parameter the application serves must be treated.
#:
#: ``workspace`` — names an object owned by a workspace. The matrix puts one in
#:   workspace B and expects the request from workspace A to be refused.
#: ``global`` — not workspace-owned; the route is an installation-wide admin surface.
#:   A plain user must still be refused, so these stay in the matrix with the same
#:   expectation, reached through the role check rather than the scope check.
#: ``public`` — not an object-authorization surface at all. Excluded, with the reason
#:   recorded here rather than in a comment somewhere else.
_PARAM_KIND: dict[str, str] = {
    "workspace_id": "workspace",
    "doc_id": "workspace",
    "chunk_id": "workspace",
    "conversation_id": "workspace",
    "memory_id": "workspace",
    "annotation_id": "workspace",
    "connector_id": "workspace",
    "key_id": "workspace",
    "user_id": "global",
    "version_id": "global",
    # The repo-docs viewer serves the repository's own committed markdown by slug.
    # There is no per-workspace object behind it and nothing user-owned to confuse.
    "slug": "public",
    "fragment_slug": "public",
}

#: A refusal. 403 (the guard said no) and 404 (the object is invisible in this scope)
#: are both correct — the plan's acceptance names either, and which one a route returns
#: is a deliberate per-route choice about whether existence may be disclosed.
_REFUSED = {403, 404}

#: `document_chunks.embedding` and `memories.embedding` are both `vector(768)` in
#: `_ensure_extensions_and_tables()`. The values are zeros: nothing here ranks anything,
#: the rows only need to exist and belong to workspace B.
_VECTOR_DIM = 768

#: Routes that validate the request body before they check authorisation, so a
#: bodyless probe gets 400 and never reaches the guard. Sending a *valid* body is
#: what makes the probe reach the thing under test. That the validation runs first
#: is not itself a leak — the 400 says nothing about the object — but it does mean
#: the matrix has to supply one.
_BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("PATCH", "/api/conversations/{conversation_id}"): {"title": "probe"},
    ("PUT", "/api/conversations/{conversation_id}/documents"): {"filenames": []},
}

#: For a `global` parameter with no object behind it — a reranker version id. The
#: assertion for those routes is that a plain user is refused by the role check,
#: which does not depend on the object existing.
_DUMMY_GLOBAL_ID = "00000000-0000-4000-8000-000000000000"

#: Two routes answer 200 for an object outside the caller's scope instead of the 404
#: P0-1's acceptance asks for. **Neither discloses anything**, which is why they are
#: recorded here rather than treated as holes:
#:
#: * `GET /api/conversations/{conversation_id}/documents` — the route *intends* to 404:
#:   `memory_routes.py` checks `if filenames is None`. That branch is unreachable,
#:   because `get_conversation_document_filter` is typed `list[str]` and returns `[]`
#:   when the row is missing (`src/db/conversations.py:293`). A foreign conversation and
#:   a nonexistent one are therefore indistinguishable, so it is not an existence oracle
#:   either — just a dead branch and a wrong status.
#: * `GET /api/chunks/{chunk_id}/annotations` — `get_annotations_for_chunk` scopes
#:   correctly, joining on `d.workspace_id`, so a foreign chunk yields no annotations.
#:   The route returns that empty list with 200 rather than refusing.
#:
#: The value is the response key that must be **empty**. That is deliberately a stronger
#: assertion than skipping the route: if either ever starts returning a foreign
#: workspace's rows, this fails. Changing the status codes is a behaviour change to a
#: shipped API and belongs in its own reviewed change, not smuggled into a test.
_DISCLOSES_NOTHING: dict[tuple[str, str], str] = {
    ("GET", "/api/conversations/{conversation_id}/documents"): "document_filter",
    ("GET", "/api/chunks/{chunk_id}/annotations"): "annotations",
}


def _spec_paths() -> dict[str, Any]:
    os.environ.setdefault("APP_ENV", "development")
    from src.app_fastapi import create_app

    return create_app().openapi()["paths"]


def object_routes() -> list[tuple[str, str]]:
    """Every (method, path) the application serves that addresses something by id."""
    return sorted(
        (method.upper(), path)
        for path, operations in _spec_paths().items()
        if _PARAM_RE.search(path)
        for method in operations
        if method.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH"}
    )


def _kinds(path: str) -> set[str]:
    return {_PARAM_KIND.get(name, "UNCLASSIFIED") for name in _PARAM_RE.findall(path)}


def matrix_routes() -> list[tuple[str, str]]:
    """The routes the matrix drives: everything but the public, non-object ones."""
    return [
        (m, p)
        for m, p in object_routes()
        if "public" not in _kinds(p) and (m, p) not in _DISCLOSES_NOTHING
    ]


class TestTheDerivationItself:
    """If these fail, the matrix below is testing fewer routes than it appears to."""

    def test_routes_are_found(self) -> None:
        assert len(object_routes()) > 40

    def test_every_path_parameter_is_classified(self) -> None:
        served = {name for _, path in object_routes() for name in _PARAM_RE.findall(path)}
        unclassified = sorted(served - set(_PARAM_KIND))
        assert unclassified == [], (
            "path parameters with no entry in _PARAM_KIND: "
            f"{', '.join(unclassified)}. Add each one as 'workspace' (an object a "
            "workspace owns — then provision one in workspace B), 'global' (an "
            "installation-wide admin surface) or 'public' (not an object-authorization "
            "surface, with the reason). Leaving it out drops its routes from the matrix."
        )

    def test_no_classification_is_stale(self) -> None:
        served = {name for _, path in object_routes() for name in _PARAM_RE.findall(path)}
        assert sorted(set(_PARAM_KIND) - served) == []


@pytest.fixture(scope="session")
def server_env() -> dict[str, str]:
    """`live_server` requires this; `tests/perf/conftest.py` supplies its own for the
    same reason.

    The limits are raised because this matrix is a burst: provisioning, the owner
    reachability sweep and 40-odd refusals all land inside a minute. At the shipped
    `RATELIMIT_GENERAL` of 60/minute the tail of the run comes back 429 — which is not
    in `_REFUSED`, so the suite would fail while the application behaved correctly.
    Rate limiting has its own test (`tests/integration/test_ratelimit.py`) and
    `security-smoke` drives it over the wire; it is not what this module measures.
    """
    return {
        "RATELIMIT_GENERAL": "100000 per minute",
        "RATELIMIT_LOGIN": "100000 per minute",
        "RATELIMIT_UPLOAD": "100000 per hour",
        "RATELIMIT_MODELS": "100000 per minute",
    }


def _client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=False)


def _status(client: httpx.Client, method: str, url: str, **kwargs: Any) -> int | str:
    """The status code, reading the response headers but never its body.

    `GET /api/workspaces/{workspace_id}/presence` is an SSE stream: it is *supposed*
    never to finish, so reading the body hangs until the timeout and the probe blames
    a healthy route. Authorisation happens before the first byte is streamed, so the
    status line is both sufficient and the only part that can be read safely. Streaming
    every request keeps one code path rather than a list of which routes stream.

    A genuine hang still returns "timeout" rather than raising out of whichever test
    reached it first, naming nothing.
    """
    try:
        with client.stream(method, url, **kwargs) as response:
            return response.status_code
    except httpx.TimeoutException:
        return "timeout"


def _login(base_url: str, username: str, password: str) -> httpx.Client:
    client = _client(base_url)
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    if response.status_code != 200:
        pytest.fail(f"could not sign in as {username}: {response.status_code} {response.text[:200]}")
    return client


@pytest.fixture(scope="session")
def provisioned(live_server: str) -> dict[str, Any]:
    """Two workspaces, two users, and one of each object type inside workspace B."""
    admin = _login(live_server, ADMIN_USERNAME, ADMIN_PASSWORD)

    workspace_a = _create_workspace(admin, "P2-2b workspace A")
    workspace_b = _create_workspace(admin, "P2-2b workspace B")

    username = f"p22b-user-{uuid.uuid4().hex[:8]}"
    password = "p22b-plain-user-password"
    user = admin.post(
        "/api/users",
        json={"username": username, "password": password, "role": "user"},
    )
    if user.status_code not in (200, 201):
        pytest.fail(f"could not create the plain user: {user.status_code} {user.text[:200]}")
    user_id = (user.json().get("user") or {}).get("id") or user.json().get("user_id")

    grant = admin.post(f"/api/users/{user_id}/workspaces",
                       json={"workspace_id": workspace_a, "role": "editor"})
    if grant.status_code not in (200, 201):
        pytest.fail(f"could not grant workspace A: {grant.status_code} {grant.text[:200]}")

    from src.db import db

    ok, message = db.initialize()
    if not ok:
        pytest.fail(f"the fixture could not reach the database the server is using: {message}")
    objects = _provision_objects(workspace_b)
    objects["workspace_id"] = workspace_b
    objects["user_id"] = user_id

    caller = _login(live_server, username, password)
    return {
        "admin": admin,
        "caller": caller,
        "workspace_a": workspace_a,
        "workspace_b": workspace_b,
        "objects": objects,
    }


def _create_workspace(admin: httpx.Client, name: str) -> str:
    response = admin.post("/api/workspaces", json={"name": name})
    if response.status_code not in (200, 201):
        pytest.fail(f"could not create {name}: {response.status_code} {response.text[:200]}")
    body = response.json()
    return (body.get("workspace") or body).get("id")


def _provision_objects(workspace_b: str) -> dict[str, Any]:
    """One object of every workspace-owned kind, inside workspace B.

    Through the application's own `src/db` mixins rather than over HTTP, for two
    reasons. There is no create endpoint for a memory at all — only
    `POST /api/memory/extract`, which runs the extractor against a conversation and
    would make this fixture depend on an LLM round-trip. And a document created over
    HTTP has to be ingested, chunked and embedded before a chunk id exists, which is
    the golden path's job (`tests/e2e/test_golden_path.py`), not this module's.

    Creation is not what is under test here; the refusal of a *foreign* object is, and
    that is driven over HTTP below. Using the mixins keeps the repository's rule that
    SQL lives in `src/db/` — this writes none.
    """
    from src.db import db

    objects: dict[str, Any] = {}

    doc_id = db.insert_document(
        filename="p22b-workspace-b.txt",
        content="Workspace B private content about quarterly margin.",
        workspace_id=workspace_b,
    )
    objects["doc_id"] = doc_id

    chunk_ids = db.insert_chunks_batch(
        [(doc_id, "Workspace B private chunk about quarterly margin.", 0, [0.0] * _VECTOR_DIM)]
    )
    if chunk_ids:
        objects["chunk_id"] = chunk_ids[0]

    objects["conversation_id"] = db.create_conversation(
        title="Workspace B private conversation", workspace_id=workspace_b
    )

    objects["memory_id"] = db.insert_memory(
        content="Workspace B private memory",
        embedding=[0.0] * _VECTOR_DIM,
        workspace_id=workspace_b,
    )

    if "chunk_id" in objects:
        objects["annotation_id"] = db.add_annotation(
            chunk_id=objects["chunk_id"], text="Workspace B private annotation"
        )

    objects["connector_id"] = db.create_connector(
        connector_type="webhook",
        display_name="Workspace B private connector",
        config={"secret": "p22b-not-a-real-secret"},
        workspace_id=workspace_b,
    )

    _, key = db.create_workspace_api_key(workspace_id=workspace_b, name="Workspace B key")
    objects["key_id"] = key.get("id")

    return objects


def _first_id(body: Any) -> Any:
    """The id of the thing just created, wherever this endpoint chose to put it."""
    if isinstance(body, dict):
        for key in ("id", "conversation_id", "memory_id", "annotation_id", "key_id"):
            if isinstance(body.get(key), (str, int)):
                return body[key]
        for value in body.values():
            found = _first_id(value)
            if found is not None:
                return found
    if isinstance(body, list) and body:
        return _first_id(body[0])
    return None


def _first_int(body: Any) -> Any:
    found = _first_id(body)
    try:
        return int(found)
    except (TypeError, ValueError):
        return found


def _fill(path: str, objects: dict[str, Any]) -> str | None:
    """Substitute workspace B's object ids into the path, or None if one is missing."""
    filled = path
    for name in _PARAM_RE.findall(path):
        value = objects.get(name)
        if value is None and _PARAM_KIND.get(name) == "global":
            value = _DUMMY_GLOBAL_ID
        if value is None:
            return None
        filled = filled.replace("{" + name + "}", str(value))
    return filled


class TestTheFixtureIsReal:
    """A 404 is a pass below, so an empty fixture would make the matrix vacuous."""

    def test_the_two_workspaces_are_distinct(self, provisioned: dict[str, Any]) -> None:
        assert provisioned["workspace_a"] != provisioned["workspace_b"]

    def test_every_workspace_owned_kind_was_provisioned(self, provisioned: dict[str, Any]) -> None:
        wanted = {name for name, kind in _PARAM_KIND.items() if kind == "workspace"}
        missing = sorted(wanted - set(provisioned["objects"]))
        assert missing == [], (
            f"workspace B has no object for: {', '.join(missing)}. Every route taking one "
            "of these would be skipped, and a skipped route proves nothing."
        )

    def test_the_fixture_objects_are_reachable_by_their_owner(
        self, provisioned: dict[str, Any]
    ) -> None:
        """The owner must see what the caller will be refused."""
        admin = provisioned["admin"]
        headers = {"X-Workspace-ID": provisioned["workspace_b"]}
        unreachable = []
        for method, path in matrix_routes():
            if method != "GET" or "global" in _kinds(path):
                continue
            filled = _fill(path, provisioned["objects"])
            if filled is None:
                continue
            status = _status(admin, "GET", filled, headers=headers, timeout=15.0)
            if status == 404 or status == "timeout":
                unreachable.append(f"{method} {path} -> {status}")
        assert unreachable == [], (
            "the owning workspace gets 404 for these, so a refusal for the foreign caller "
            f"proves nothing about authorization: {', '.join(unreachable)}"
        )


@pytest.mark.parametrize(("method", "path"), matrix_routes(), ids=lambda v: str(v))
def test_a_foreign_workspaces_object_is_refused(
    method: str, path: str, provisioned: dict[str, Any]
) -> None:
    """Workspace A's user addresses workspace B's object. Every route must refuse."""
    filled = _fill(path, provisioned["objects"])
    if filled is None:
        pytest.fail(
            f"no workspace B object for {method} {path}; _provision_objects must create one, "
            "or the parameter belongs in _PARAM_KIND as 'public' with a reason"
        )

    body = _BODIES.get((method, path))
    if body is None and method in {"POST", "PUT", "PATCH"}:
        body = {}
    status = _status(
        provisioned["caller"],
        method,
        filled,
        headers={"X-Workspace-ID": provisioned["workspace_a"]},
        json=body,
        timeout=15.0,
    )
    assert status in _REFUSED, (
        f"{method} {path} returned {status} for an object in a foreign workspace; "
        f"expected one of {sorted(_REFUSED)}"
    )


@pytest.mark.parametrize(("method", "path"), sorted(_DISCLOSES_NOTHING), ids=lambda v: str(v))
def test_a_known_deviation_answers_200_but_discloses_nothing(
    method: str, path: str, provisioned: dict[str, Any]
) -> None:
    """The two routes that answer instead of refusing must answer with nothing.

    Recorded rather than skipped: a skip would stop noticing if one of them began
    returning the foreign workspace's rows, which is the failure that would matter.
    If a route is fixed to refuse, this test fails and its row comes out of
    `_DISCLOSES_NOTHING` — the deviation cannot rot into a permanent exemption.
    """
    filled = _fill(path, provisioned["objects"])
    assert filled is not None, f"no workspace B object for {method} {path}"

    response = provisioned["caller"].request(
        method, filled, headers={"X-Workspace-ID": provisioned["workspace_a"]}, timeout=15.0
    )
    assert response.status_code == 200, (
        f"{method} {path} now returns {response.status_code}; if it was fixed to refuse, "
        "remove its row from _DISCLOSES_NOTHING so the refusal matrix covers it"
    )
    assert response.json()[_DISCLOSES_NOTHING[(method, path)]] == [], (
        f"{method} {path} disclosed a foreign workspace's rows: {response.text[:200]}"
    )
