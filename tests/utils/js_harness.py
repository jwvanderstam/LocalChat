"""Run a real ``static/js`` file under node with stubbed browser globals.

Branch logic in the frontend is unreachable from the Python suites, and asserting on
the source text only restates it. This executes the actual file instead: stub
``localStorage``, a permissive proxy DOM, and a ``fetch`` routed by URL, then report
what the module did.

See ``.claude/rules/testing.md`` -> "Frontend logic".
"""

from __future__ import annotations

import json
import shutil
import subprocess
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
        id: id || '', textContent: '', innerHTML: '', value: '', style: {}, dataset: {},
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
globalThis.navigator = { clipboard: { writeText: () => Promise.resolve() } };
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
})), DELAY);
"""


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
    program = (
        f"const PRELOAD = {json.dumps(preload or {})};\n"
        f"const ROUTES = {json.dumps(routes or [])};\n"
        f"const DELAY = {delay};\n"
        f"{_HARNESS}\n{source}\n{click_js}{_REPORT}"
    )
    out = subprocess.run(["node", "-e", program], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, f"node failed: {out.stderr}"
    line = next(ln for ln in out.stdout.splitlines() if ln.startswith("__RESULT__"))
    return json.loads(line[len("__RESULT__") :])
