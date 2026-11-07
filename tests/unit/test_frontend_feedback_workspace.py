"""R-8 — a rating travels with the active workspace, or the server checks its ids in the wrong one.

The server looks up every id a rating names in the request's scope, and without the header
that scope is the default workspace: every rating in any other workspace would be a 404,
which the bar does not show.
"""

from __future__ import annotations

import pytest

from tests.utils.js_harness import NODE_MISSING, run_js_snippet

pytestmark = [pytest.mark.unit, pytest.mark.skipif(NODE_MISSING, reason="node is not installed")]

CLICK_THUMBS_UP = """
import { buildFeedbackBar } from './ui.js';
%s
let sent = null;
globalThis.fetch = (url, opts) => { sent = opts.headers; return Promise.resolve({ status: 201 }); };
buildFeedbackBar(5, 'c1', [7]);
await submitted.click[0]();
globalThis.result = sent;
"""


def test_a_rating_names_the_active_workspace() -> None:
    sent = run_js_snippet(CLICK_THUMBS_UP % "localStorage.setItem('localchat_active_workspace_id', 'ws-2');")
    assert sent == {"Content-Type": "application/json", "X-Workspace-ID": "ws-2"}


def test_a_rating_without_an_active_workspace_sends_no_header() -> None:
    assert run_js_snippet(CLICK_THUMBS_UP % "") == {"Content-Type": "application/json"}
