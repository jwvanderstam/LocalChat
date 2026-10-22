"""GKB-2 — the Documents page's global-knowledge controls, run under node.

The server decides who may contribute and withdraw (`/api/users/me`); the page only
shows what it was told. The controls start hidden, because they act on the tier every
workspace reads, so a failed or slow permission check must leave them hidden.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.utils.js_harness import NODE_MISSING, run_js

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(NODE_MISSING, reason="node is not installed"),
]

WS = "11111111-1111-1111-1111-111111111111"


def _doc(doc_id: int, filename: str, shared: bool) -> dict[str, Any]:
    return {"id": doc_id, "filename": filename, "created_at": "2026-10-20T10:00:00",
            "chunk_count": 3, "shared_globally": shared}


def _page(me: dict[str, Any], *, workspace: str | None = WS,
          documents: tuple[dict[str, Any], ...] = ()) -> dict[str, Any]:
    return run_js(
        "ingestion.js",
        preload={"localchat_active_workspace_id": workspace} if workspace else {},
        routes=[
            ("/api/users/me", {"success": True, "can_write": True, **me}),
            ("/api/documents/list", {"success": True, "documents": list(documents)}),
            ("/api/documents/stats", {"success": True}),
        ],
    )


def _controls(result: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    display = result["display"]
    return display["gkb-block"], display["contribute-btn"], display["withdraw-btn"]


@pytest.mark.parametrize(("me", "expected"), [
    ({"can_contribute": True, "can_withdraw": True}, ("", "", "")),
    ({"can_contribute": False, "can_withdraw": True}, ("", "none", "")),
    ({"can_contribute": False, "can_withdraw": False}, ("none", "none", "none")),
    ({}, ("none", "none", "none")),
], ids=["admin", "owner", "editor", "server-said-nothing"])
def test_each_control_follows_the_server(me, expected):
    assert _controls(_page(me)) == expected


def test_without_an_active_workspace_there_is_nothing_to_address():
    assert _controls(_page({"can_contribute": True, "can_withdraw": True}, workspace=None)) == (
        "none", "none", "none")


def test_a_shared_document_carries_the_tag_and_only_that_one():
    html = _page({}, documents=(_doc(1, "draft.md", False), _doc(2, "retro.md", True)))[
        "html"]["documents-list"]

    assert html.count("data-shared-globally") == 1
    assert html.index("draft.md") < html.index("retro.md") < html.index("data-shared-globally")


@pytest.mark.parametrize(("can_contribute", "boxes"), [(True, 2), (False, 0)])
def test_only_a_contributor_gets_a_selector_per_document(can_contribute, boxes):
    html = _page({"can_contribute": can_contribute},
                 documents=(_doc(1, "draft.md", False), _doc(2, "retro.md", True)))[
        "html"]["documents-list"]

    assert html.count("data-contribute-document=") == boxes

