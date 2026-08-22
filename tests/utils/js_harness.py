"""Run a real ``static/js`` file under node with stubbed browser globals.

Branch logic in the frontend is unreachable from the Python suites, and asserting on
the source text only restates it. This executes the actual file instead: stub
``localStorage``, a permissive proxy DOM, and a ``fetch`` routed by URL, then report
what the module did.

See ``.claude/rules/testing.md`` -> "Frontend logic".
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

JS_DIR = Path(__file__).resolve().parents[2] / "static" / "js"

#: Node ships on GitHub-hosted runners; a local environment may not have it.
NODE_MISSING = shutil.which("node") is None

_HARNESS = """
const store = new Map(Object.entries(PRELOAD));
const submitted = {};
const calls = [];
globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
};

// The proxy target is a function so an unknown property is both callable
// (`list.querySelector(...)`) and chainable (`x.dataset.id`) without enumerating a DOM.
const nodes = {};
const el = (id) => {
    if (id && nodes[id]) return nodes[id];
    const target = Object.assign(function () { return el(); }, {
        // `checked` starts false, as an unchecked checkbox does. A module that
        // restores a stored toggle has to set it; one that forgets leaves it false,
        // which is the difference these tests exist to see.
        id: id || '', textContent: '', innerHTML: '', value: '', checked: false,
        style: {}, dataset: {},
        classList: { add() {}, remove() {}, contains: () => false },
        appendChild() {}, reset() {}, select() {},
        // Recorded rather than dropped: a form's whole behaviour lives in its handler,
        // so a stub that swallows listeners would test an empty program.
        addEventListener: (name, fn) => { (submitted[name] ||= []).push(fn); },
    });
    const proxy = new Proxy(target, {
        apply: () => el(),
        get: (t, p) => (p in t ? t[p] : el()),
        set: (t, p, v) => {
            t[p] = v;
            // Escaping helpers set textContent and read innerHTML back. Without this
            // the round-trip returns '' and every escaped field renders empty — the
            // markup still looks plausible, so it has to be modelled, not stubbed.
            if (p === 'textContent') {
                t.innerHTML = String(v)
                    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            }
            return true;
        },
    });
    if (id) nodes[id] = proxy;
    return proxy;
};
globalThis.document = {
    readyState: 'complete',
    getElementById: (id) => el(id),
    querySelectorAll: () => [],
    addEventListener: (name, fn) => { if (name === 'DOMContentLoaded') fn(); },
    createElement: () => el(),
};
globalThis.window = globalThis;
// defineProperty, not assignment: node exposes a real read-only `navigator` when
// running a file, and only a writable stub under `node -e`. The harness runs both ways.
Object.defineProperty(globalThis, 'navigator', {
    value: { clipboard: { writeText: () => Promise.resolve() } },
    configurable: true, writable: true,
});
globalThis.confirm = () => true;

// Any bootstrap widget: usable as `new bootstrap.Tooltip(x)` and as
// `bootstrap.Modal.getInstance(x).hide()`, so the modules load either way.
const widget = () => Object.assign(function () { return { hide() {}, show() {} }; },
    { getInstance: () => ({ hide() {}, show() {} }),
      getOrCreateInstance: () => ({ hide() {}, show() {} }) });
globalThis.bootstrap = new Proxy({}, { get: () => widget() });
globalThis.location = { search: '', href: '/', pathname: '/' };

globalThis.fetch = (url, opts) => {
    calls.push({ url: String(url), method: (opts && opts.method) || 'GET',
                 body: (opts && opts.body) || null });
    let payload = {};
    for (const [pattern, value] of ROUTES) {
        if (String(url).includes(pattern)) { payload = value; break; }
    }
    return Promise.resolve({
        ok: true, status: 200, headers: { get: () => 'application/json' },
        json: () => Promise.resolve(payload),
    });
};
"""

_REPORT = """
(submitted.submit || []).forEach((fn) => fn({ preventDefault() {} }));
setTimeout(() => console.log('__RESULT__' + JSON.stringify({
    storage: Object.fromEntries(store),
    calls: calls,
    html: Object.fromEntries(Object.entries(nodes).map(([k, v]) => [k, v.innerHTML])),
    values: Object.fromEntries(Object.entries(nodes).map(([k, v]) => [k, v.value])),
    // Checkbox state, which `values` does not carry. Without it a test of a toggle
    // can only read back the storage it seeded itself — an assertion that holds
    // whether or not the module did anything at all.
    checked: Object.fromEntries(Object.entries(nodes).map(([k, v]) => [k, v.checked])),
})), DELAY);
"""


#: A local import — the one thing that makes a module unrunnable from `node -e`.
#: Matched on the `from` clause rather than the `import` keyword, because a named
#: import wraps across lines and an anchored pattern silently misses it: two of the
#: four modules here import that way, and were still being inlined and failing.
_LOCAL_IMPORT = re.compile(r"""from\s+['"]\./""")


def _run_beside_sources(program: str) -> subprocess.CompletedProcess:
    """Run *program* as a module inside static/js, so its relative imports resolve.

    The file is removed whatever happens: static/js is a mounted directory, so a
    stray harness module there would be served to browsers.
    """
    path = JS_DIR / f"__harness_{uuid.uuid4().hex}.mjs"
    try:
        path.write_text(program, encoding="utf-8")
        return subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=30)
    finally:
        path.unlink(missing_ok=True)


def run_js(
    script: str,
    *,
    preload: dict[str, str] | None = None,
    routes: list[tuple[str, Any]] | None = None,
    click: str | None = None,
    delay: int = 60,
) -> dict[str, Any]:
    """Execute ``static/js/<script>`` and return what it did.

    ``routes`` maps a URL substring to the JSON that ``fetch`` should answer with;
    the first match wins. ``click`` names an element id whose click handler is fired
    after load. The result carries ``storage``, ``calls``, ``html`` and ``values``.
    """
    source = (JS_DIR / script).read_text(encoding="utf-8")
    click_js = (
        f"(nodes[{json.dumps(click)}] && (submitted.click || [])).forEach((fn) => "
        "fn({ preventDefault() {}, target: { closest: () => null } }));\n"
        if click
        else ""
    )
    preamble = (
        f"const PRELOAD = {json.dumps(preload or {})};\n"
        f"const ROUTES = {json.dumps(routes or [])};\n"
        f"const DELAY = {delay};\n"
        f"{_HARNESS}\n"
    )

    # A module that imports its siblings cannot be inlined into `node -e`: there is no
    # file to resolve "./ui.js" against, so it fails before running. chat.js was
    # untestable for that reason alone. Running from a throwaway module *inside*
    # static/js gives those imports a home, and a dynamic import keeps the globals
    # installed before the module body evaluates — a static import is hoisted and
    # would see none of them.
    if _LOCAL_IMPORT.search(source):
        target = json.dumps("./" + script)
        out = _run_beside_sources(f"{preamble}await import({target});\n{click_js}{_REPORT}")
    else:
        program = f"{preamble}{source}\n{click_js}{_REPORT}"
        out = subprocess.run(["node", "-e", program], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, f"node failed: {out.stderr}"
    line = next(ln for ln in out.stdout.splitlines() if ln.startswith("__RESULT__"))
    return json.loads(line[len("__RESULT__") :])
