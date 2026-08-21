"""Frontend behaviour of the shared confirmation dialog (`static/js/confirm.js`).

Destructive actions used the native ``confirm()`` while rename and every other
prompt used an in-app modal. Besides the inconsistency, a native dialog sits
outside the page: automation drives it blind, and a QA pass lost a document by
accepting one it meant to dismiss.
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

# A DOM small enough to be obvious, with a bootstrap Modal that records show/hide and
# lets the test fire the button or a dismissal.
_HARNESS = """
const nodes = {};
const listeners = {};
function mk(id) {
    return nodes[id] = {
        id, textContent: '', innerHTML: '', className: '',
        addEventListener: (n, fn) => { (listeners[id + ':' + n] ||= []).push(fn); },
        removeEventListener: () => {},
    };
}
['confirmModal', 'confirmModalLabel', 'confirm-modal-body', 'confirm-modal-accept'].forEach(mk);
globalThis.document = { getElementById: (id) => nodes[id] || null };
globalThis.window = globalThis;
let shown = 0;
globalThis.bootstrap = {
    Modal: {
        getOrCreateInstance: () => ({
            show() { shown++; },
            hide() { (listeners['confirmModal:hidden.bs.modal'] || []).forEach((f) => f()); },
        }),
    },
};
globalThis.confirm = () => { throw new Error('native confirm() must not be reached'); };
"""

_REPORT = """
setTimeout(() => console.log('__RESULT__' + JSON.stringify({
    resolved, shown,
    title: nodes['confirmModalLabel'].textContent,
    body: nodes['confirm-modal-body'].innerHTML,
    buttonText: nodes['confirm-modal-accept'].textContent,
    buttonClass: nodes['confirm-modal-accept'].className,
})), 40);
"""


def _run(options: dict, *, action: str) -> dict:
    """Open the dialog, then either accept it or dismiss it."""
    source = (JS_DIR / "confirm.js").read_text(encoding="utf-8")
    drive = {
        "accept": "(listeners['confirm-modal-accept:click'] || []).forEach((f) => f());",
        # Backdrop click, Escape and the close button all surface as this one event.
        "dismiss": "(listeners['confirmModal:hidden.bs.modal'] || []).forEach((f) => f());",
    }[action]
    program = (
        f"{_HARNESS}\n{source}\n"
        "let resolved = null;\n"
        f"window.localchatConfirm({json.dumps(options)}).then((v) => {{ resolved = v; }});\n"
        f"setTimeout(() => {{ {drive} }}, 5);\n{_REPORT}"
    )
    out = subprocess.run(["node", "-e", program], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    line = next(ln for ln in out.stdout.splitlines() if ln.startswith("__RESULT__"))
    return json.loads(line[len("__RESULT__"):])


class TestOutcome:
    def test_accepting_resolves_true(self):
        assert _run({"title": "Delete", "body": "gone"}, action="accept")["resolved"] is True

    def test_dismissing_resolves_false(self):
        """Backdrop, Escape and the close button all reach here — one answer for all."""
        assert _run({"title": "Delete", "body": "gone"}, action="dismiss")["resolved"] is False

    def test_the_dialog_is_actually_shown(self):
        assert _run({"title": "Delete", "body": "gone"}, action="accept")["shown"] == 1

    def test_the_native_dialog_is_never_used_when_the_modal_exists(self):
        """The harness throws if confirm() is called; reaching a result proves it was not."""
        assert _run({"title": "Delete", "body": "gone"}, action="accept")["resolved"] is True


class TestRendering:
    def test_title_and_body_are_shown(self):
        result = _run({"title": "Delete document", "body": "roadmap.md will go"}, action="accept")
        assert result["title"] == "Delete document"
        assert "roadmap.md will go" in result["body"]

    def test_the_body_is_escaped(self):
        """Bodies interpolate filenames and usernames — text this app did not author."""
        result = _run({"title": "x", "body": '<img src=x onerror="alert(1)">'}, action="accept")
        assert "<img" not in result["body"]
        assert "&lt;img" in result["body"]

    def test_newlines_become_breaks_rather_than_being_swallowed(self):
        result = _run({"title": "x", "body": "first\nsecond"}, action="accept")
        assert "<br>" in result["body"]

    def test_the_confirm_label_is_the_action_not_the_word_ok(self):
        """"Delete" on the button is what a native confirm() could never say."""
        result = _run({"title": "x", "body": "y", "confirmText": "Delete"}, action="accept")
        assert result["buttonText"] == "Delete"

    def test_destructive_by_default(self):
        assert "btn-danger" in _run({"title": "x", "body": "y"}, action="accept")["buttonClass"]

    def test_danger_false_softens_the_button(self):
        """Retire is reversible, so it should not look like deletion."""
        result = _run({"title": "x", "body": "y", "danger": False}, action="accept")
        assert "btn-primary" in result["buttonClass"]
