"""Session handling around the admin-only chrome (`static/js/auth.js`).

`revealAdminChrome` deliberately bypasses the fetch wrapper that redirects on 401,
so it has to handle that status itself. It did not: an expired session ended the
function silently, the admin tabs never appeared, and the interface looked like it
had lost Observability and Users rather than the session.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from tests.utils.js_harness import JS_DIR, NODE_MISSING

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(NODE_MISSING, reason="node is not installed"),
]

_HARNESS = """
let redirectedTo = null;
const revealed = [];
const tabs = [];
function el(id, cls) {
    return {
        id, className: cls || '', getAttribute: () => '#pane',
        classList: {
            _s: new Set((cls || '').split(' ').filter(Boolean)),
            add(c) { this._s.add(c); },
            remove(c) { this._s.delete(c); if (c === 'd-none') revealed.push(id); },
            contains(c) { return this._s.has(c); },
        },
        closest: () => null, querySelector: () => null, querySelectorAll: () => [],
    };
}
const adminEls = [el('observability-tab-item', 'd-none admin-only'),
                  el('rag-tab-item', 'd-none admin-only')];
globalThis.document = {
    readyState: 'complete',
    querySelectorAll: (sel) => (sel === '.admin-only' ? adminEls : []),
    querySelector: () => null,
    getElementById: () => null,
    // auth.js does its work from DOMContentLoaded; swallowing the handler would
    // test an empty program.
    addEventListener: (name, fn) => { if (name === 'DOMContentLoaded') fn(); },
};
globalThis.window = globalThis;
globalThis.location = { pathname: '/settings', search: '', href: '/settings' };
Object.defineProperty(globalThis.location, 'href', {
    get: () => '/settings', set: (v) => { redirectedTo = v; }, configurable: true,
});
globalThis.fetch = () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
"""

_REPORT = """
setTimeout(() => console.log('__RESULT__' + JSON.stringify({
    redirectedTo, revealed,
})), 40);
"""


def _run(status: int, role: str | None) -> dict:
    """Load auth.js with /api/users/me answering *status* and *role*."""
    source = (JS_DIR / "auth.js").read_text(encoding="utf-8")
    body = json.dumps({"role": role} if role else {})
    stub = (
        "globalThis.fetch = (url) => Promise.resolve({"
        f"  ok: {str(status < 400).lower()}, status: {status},"
        f"  json: () => Promise.resolve({body})"
        "});"
    )
    program = f"{_HARNESS}\n{stub}\n{source}\n{_REPORT}"
    out = subprocess.run(["node", "-e", program], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    line = next(ln for ln in out.stdout.splitlines() if ln.startswith("__RESULT__"))
    return json.loads(line[len("__RESULT__"):])


class TestExpiredSession:
    def test_a_401_sends_the_user_to_log_in(self):
        """The regression: it used to return silently, stripping the admin tabs."""
        result = _run(401, None)
        assert result["redirectedTo"], "expired session did not redirect to login"
        assert "/login" in result["redirectedTo"]

    def test_the_redirect_remembers_where_the_user_was(self):
        assert "next=%2Fsettings" in _run(401, None)["redirectedTo"]

    def test_no_admin_chrome_is_revealed_on_a_401(self):
        """Redirecting must not also expose the surface on the way out."""
        assert _run(401, None)["revealed"] == []


class TestOrdinaryOutcomes:
    def test_an_admin_still_gets_the_chrome(self):
        """Guard against over-correction: this must not log admins out."""
        result = _run(200, "admin")
        assert result["redirectedTo"] is None
        assert len(result["revealed"]) == 2

    def test_a_non_admin_is_not_redirected_and_sees_nothing_extra(self):
        """A plain user is authenticated — the tabs are simply not theirs."""
        result = _run(200, "user")
        assert result["redirectedTo"] is None
        assert result["revealed"] == []

    def test_a_server_error_leaves_the_chrome_hidden_without_redirecting(self):
        """A 500 is not an authentication problem; do not bounce them to login."""
        result = _run(500, None)
        assert result["redirectedTo"] is None
        assert result["revealed"] == []
