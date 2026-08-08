"""The active workspace in localStorage must belong to whoever is signed in now.

localStorage is scoped to the browser, not to the session. An admin working in
"Default" who signs out, and an editor with access only to another workspace who
signs in after them, shared one key: the editor inherited "Default", every page
sent it as ``X-Workspace-ID`` before the switcher had loaded, and the server
answered 403 to each one. The account looked broken until the workspace was
picked by hand.

These run the real ``static/js`` files under node with stubbed browser globals,
because both defects live in branch logic no Python test can reach — the previous
workspace bug shipped past 2550 green Python tests for the same reason. Asserting
on the source text instead would only restate the code.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS_DIR = Path(__file__).resolve().parents[2] / "static" / "js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

#: A stub DOM: enough for the modules to load and run, and nothing more. Every
#: element answers, so a missing id fails on behaviour rather than on a null.
HARNESS = """
const store = new Map(Object.entries(PRELOAD));
const submitted = {};
globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
};
// The proxy target is a function so an unknown property is both callable
// (`list.querySelector(...)`) and chainable (`x.dataset.id`) without enumerating a DOM.
const el = () => {
    const target = Object.assign(function () { return el(); }, {
        textContent: '', innerHTML: '', value: '', style: {}, dataset: {},
        classList: { add() {}, remove() {}, contains: () => false },
        appendChild() {}, reset() {},
        // Recorded rather than dropped: the login path lives entirely inside a submit
        // handler, so a stub that swallows listeners would test an empty program.
        addEventListener: (name, fn) => { (submitted[name] ||= []).push(fn); },
    });
    return new Proxy(target, {
        apply: () => el(),
        get: (t, p) => (p in t ? t[p] : el()),
        set: (t, p, v) => ((t[p] = v), true),
    });
};
globalThis.document = {
    readyState: 'complete',
    getElementById: () => el(),
    querySelectorAll: () => [],
    addEventListener: (name, fn) => { if (name === 'DOMContentLoaded') fn(); },
    createElement: () => el(),
};
globalThis.window = globalThis;
// Any bootstrap widget: usable as `new bootstrap.Tooltip(x)` and as
// `bootstrap.Modal.getInstance(x).hide()`, so the modules load either way.
const widget = () => Object.assign(function () { return { hide() {}, show() {} }; },
    { getInstance: () => ({ hide() {}, show() {} }),
      getOrCreateInstance: () => ({ hide() {}, show() {} }) });
globalThis.bootstrap = new Proxy({}, { get: () => widget() });
globalThis.location = { search: '', href: '/', pathname: '/' };
globalThis.fetch = (url, opts) => Promise.resolve({
    ok: true, status: 200, headers: { get: () => 'application/json' },
    json: () => Promise.resolve(RESPONSE),
});
"""

#: Fire any registered submit handler (the login form), then report localStorage.
REPORT = """
(submitted.submit || []).forEach((fn) => fn({ preventDefault() {} }));
setTimeout(() => console.log(JSON.stringify(Object.fromEntries(store))), 50);
"""

ID_KEY = "localchat_active_workspace_id"
NAME_KEY = "localchat_active_workspace"

MINE = {"id": "ws-mine", "name": "Localchat"}
THEIRS = {"id": "ws-theirs", "name": "Default"}


def _run(script: str, preload: dict, response: dict) -> dict:
    """Execute a static/js file under the harness; return localStorage afterwards."""
    source = (JS_DIR / script).read_text(encoding="utf-8")
    program = (
        f"const PRELOAD = {json.dumps(preload)};\n"
        f"const RESPONSE = {json.dumps(response)};\n"
        f"{HARNESS}\n{source}\n{REPORT}"
    )
    out = subprocess.run(
        ["node", "-e", program], capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, f"node failed: {out.stderr}"
    return json.loads(out.stdout.strip().splitlines()[-1])


def _switcher(preload: dict, workspaces: list[dict]) -> dict:
    return _run("workspace.js", preload, {"success": True, "workspaces": workspaces})


@pytest.mark.unit
class TestStaleChoiceIsNotHonoured:
    """The reported bug: a workspace the server did not offer must not stay active."""

    def test_inherited_workspace_is_replaced_by_one_the_user_can_enter(self):
        after = _switcher({ID_KEY: THEIRS["id"], NAME_KEY: THEIRS["name"]}, [MINE])
        assert after[ID_KEY] == MINE["id"]

    def test_the_displayed_name_is_replaced_too(self):
        """A right id under the previous user's name is its own confusing failure."""
        after = _switcher({ID_KEY: THEIRS["id"], NAME_KEY: THEIRS["name"]}, [MINE])
        assert after[NAME_KEY] == MINE["name"]

    def test_a_user_with_no_workspaces_keeps_no_stale_id(self):
        """Otherwise every request carries a 403 header with nothing to correct it."""
        after = _switcher({ID_KEY: THEIRS["id"], NAME_KEY: THEIRS["name"]}, [])
        assert ID_KEY not in after and NAME_KEY not in after


@pytest.mark.unit
class TestValidChoicesSurvive:
    """The negative space: validation must not become "always reset to the first"."""

    def test_a_still_valid_choice_is_kept_even_when_it_is_not_first(self):
        after = _switcher({ID_KEY: MINE["id"], NAME_KEY: MINE["name"]}, [THEIRS, MINE])
        assert after[ID_KEY] == MINE["id"]

    def test_first_login_with_no_stored_choice_picks_the_first_offered(self):
        after = _switcher({}, [MINE, THEIRS])
        assert after[ID_KEY] == MINE["id"]


@pytest.mark.unit
class TestLoginClearsThePreviousAccount:
    """The switcher corrects the id late; login removes it before anything sends it."""

    def _login(self, preload: dict) -> dict:
        return _run("auth.js", preload, {"success": True})

    def test_signing_in_drops_the_previous_users_workspace_id(self):
        after = self._login({ID_KEY: THEIRS["id"], NAME_KEY: THEIRS["name"]})
        assert ID_KEY not in after

    def test_signing_in_drops_the_previous_users_workspace_name(self):
        after = self._login({ID_KEY: THEIRS["id"], NAME_KEY: THEIRS["name"]})
        assert NAME_KEY not in after
