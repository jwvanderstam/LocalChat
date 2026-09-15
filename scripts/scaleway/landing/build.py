#!/usr/bin/env python3
"""Build the landing host's generated pages from the repository.

`index.html` is written by hand. The two pages beside it are not:

* ``log.html``    — every entry of docs/DEPLOYMENT_LOG.md, rendered.
* ``deploy.html`` — the deployment scripts as they are at the build commit, each
                    linked to its current version on GitHub.

Both are served from the public internet by a host in the default project, so the
rule in DEPLOYMENT_SCALEWAY.md §13 applies: no resource IDs, no private addresses,
no keys, no container endpoints. The log is full of those, deliberately — they are
what make an entry useful to the next session — so they are replaced with
placeholders here rather than removed from the source. What happened survives;
how to reach something does not. The scripts contain none of these (their tunables
are all environment variables), which is checked, not assumed.

Usage:
    python scripts/scaleway/landing/build.py            # writes log.html, deploy.html
    python scripts/scaleway/landing/build.py --check    # exits 1 if either is stale

Both pages take their stylesheet from index.html's <style> block, so there is one
look and one place to change it.
"""

from __future__ import annotations

import html
import pathlib
import re
import subprocess
import sys
from datetime import date

import markdown

ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent
LOG = ROOT / "docs" / "DEPLOYMENT_LOG.md"
GITHUB = "https://github.com/jwvanderstam/LocalChat"

# Order is the order a deployment runs them; the purpose line is what a reader
# needs before opening the file, and the sections of DEPLOYMENT_SCALEWAY.md that
# explain the decisions behind each.
SCRIPTS = [
    ("provision.sh", "Phase 1 — the scoped project, the database, and an identity that can reach that database and nothing else."),
    ("deploy_container.sh", "Phase 2 — the application as a Serverless Container, from a version tag."),
    ("verify_deployment.py", "Phase 3 — the gate: signs in, checks the image, ingests a document and retrieves it semantically. Exits non-zero on failure."),
    ("deploy_embeddings.sh", "Phase 4 — an Instance serving embeddings over a private network, wired to the container."),
    ("ollama-cloud-init.yaml", "The cloud-init that Phase 4 hands to that Instance. Installs Ollama and deliberately pulls no model."),
    ("verify_database.py", "A standalone check of a managed database: TLS required, pgvector present, a setting that survives a transaction boundary."),
    ("panic_teardown.sh", "The cost kill switch — deletes everything billable in one project, most expensive first. Dry run unless CONFIRM=DESTROY."),
]

REDACTIONS = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "<id>"),
    (re.compile(r"https?://[a-z0-9-]+\.functions\.fnc\.[a-z0-9-]+\.scw\.cloud"), "<endpoint>"),
    (re.compile(r"\b[a-z0-9-]+\.functions\.fnc\.[a-z0-9-]+\.scw\.cloud\b"), "<endpoint>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b"), "<address>"),
    # Short resource ids: eight hex digits standing alone. A seven-digit git SHA
    # is not matched, and nothing else in the log is eight hex characters.
    (re.compile(r"(?<![0-9a-f-])[0-9a-f]{8}(?![0-9a-f-])"), "<id>"),
]

_REDACTED_SHAPE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-|(?:\d{1,3}\.){3}\d{1,3}|\.scw\.cloud")
# For the scripts: a real identifier or a routable address. A usage line naming the
# shape of an endpoint (`https://…functions.fnc.fr-par.scw.cloud`) is documentation.
_SCRIPT_LEAK = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-|(?!0\.0\.0\.0|127\.0\.0\.1)(?:\d{1,3}\.){3}\d{1,3}")


def redact(text: str) -> str:
    for pattern, placeholder in REDACTIONS:
        text = pattern.sub(placeholder, text)
    return text


def stylesheet() -> str:
    index = (HERE / "index.html").read_text(encoding="utf-8")
    match = re.search(r"<style>.*?</style>", index, re.S)
    if not match:
        sys.exit("index.html has no <style> block to share")
    return match.group(0)


def build_commit() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    return out.stdout.strip() or "unknown"


def page(title: str, eyebrow: str, standfirst: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{html.escape(title)} — LocalChat on Scaleway</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Serif:wght@600&display=swap">
{stylesheet()}
<style>
  .script {{ margin-top: 3rem; }}
  .script-links {{ font-family: "IBM Plex Mono", monospace; font-size: 0.8rem; color: var(--ink-faint); display: flex; flex-wrap: wrap; gap: 0.4rem 1.2rem; margin: 0.3rem 0 0.8rem; }}
  .script-links a {{ color: var(--accent); }}
  pre.source {{ max-height: 34rem; overflow: auto; font-size: 0.78rem; }}
  h2 {{ margin-top: 3.2rem; }}
  blockquote {{ margin: 1.2rem 0; padding: 0.2rem 1.1rem; border-left: 3px solid var(--warn); background: var(--warn-soft); max-width: 66ch; }}
  blockquote h2 {{ font-size: 1.1rem; margin: 0.6rem 0 0.4rem; }}
  hr {{ border: 0; border-top: 1px solid var(--rule); margin: 2.4rem 0; }}
  .toc {{ font-size: 0.9rem; columns: 2; column-gap: 2rem; }}
  .toc a {{ color: var(--ink-soft); }}
</style>
</head>
<body>
<div class="page">
  <nav class="site">
    <a href="index.html"{' aria-current="page"' if title == 'Overview' else ''}>Overview</a>
    <a href="log.html"{' aria-current="page"' if title == 'Deployment log' else ''}>Deployment log</a>
    <a href="deploy.html"{' aria-current="page"' if title == 'The scripts' else ''}>The scripts</a>
  </nav>
  <header>
    <div class="eyebrow">{eyebrow}</div>
    <h1>{html.escape(title)}</h1>
    <p class="standfirst">{standfirst}</p>
  </header>
{body}
  <footer>
    Generated from the repository at commit {build_commit()} on {date.today().isoformat()}
    &middot; <a href="{GITHUB}">{GITHUB.removeprefix('https://')}</a>
  </footer>
</div>
</body>
</html>
"""


def build_log() -> str:
    raw = LOG.read_text(encoding="utf-8")
    body, _, _ = raw.partition("\n## How to add an entry")
    body = body.split("\n", 1)[1]  # drop the H1; the page has its own
    redacted = redact(body)
    rendered = markdown.markdown(redacted, extensions=["fenced_code", "tables"])
    # The log links its siblings the way the repository does; on this host they
    # would be 404s, so they go to the repository instead.
    rendered = re.sub(
        r'href="([A-Za-z_]+\.md)(#[^"]*)?"',
        lambda m: f'href="{GITHUB}/blob/main/docs/{m.group(1)}{m.group(2) or ""}"',
        rendered,
    )
    # A leak that survived redaction is a build failure, not a page.
    leaked = _REDACTED_SHAPE.search(re.sub(r"<[^>]+>", "", rendered))
    if leaked:
        sys.exit(f"log.html would publish an identifier: {leaked.group(0)!r}")
    entries = re.findall(r"^## (\d{4}-\d{2}-\d{2}[^\n]*)", body, re.M)
    toc = "\n".join(
        f'    <li><a href="#{re.sub(r"[^a-z0-9]+", "-", e.lower()).strip("-")}">{html.escape(e)}</a></li>'
        for e in entries
    )
    rendered = re.sub(
        r"<h2>(\d{4}-\d{2}-\d{2}[^<]*)</h2>",
        lambda m: f'<h2 id="{re.sub(r"[^a-z0-9]+", "-", m.group(1).lower()).strip("-")}">{m.group(1)}</h2>',
        rendered,
    )
    intro = (
        "<section><p>One entry per session, oldest first, exactly as kept in the "
        "repository — with one difference: resource identifiers, private addresses and "
        "endpoints are replaced by <code>&lt;id&gt;</code>, <code>&lt;address&gt;</code> "
        "and <code>&lt;endpoint&gt;</code>. Everything described here is torn down; the "
        "placeholders keep this page about what happened rather than where.</p>"
        f'<ul class="toc">\n{toc}\n  </ul></section>\n'
    )
    return page(
        "Deployment log",
        "<span>Record</span><span>Scaleway fr-par</span><span>Every session</span>",
        "What each session did, what it found that the plan did not predict, and what it cost.",
        intro + "<section>" + rendered + "</section>",
    )


def build_deploy() -> str:
    commit = build_commit()
    sections = []
    for name, purpose in SCRIPTS:
        source = (HERE.parent / name).read_text(encoding="utf-8")
        if _SCRIPT_LEAK.search(source):
            sys.exit(f"{name} carries an identifier or address and must not be published")
        blob = f"{GITHUB}/blob/main/scripts/scaleway/{name}"
        raw = f"{GITHUB}/raw/main/scripts/scaleway/{name}"
        sections.append(
            f'  <section class="script" id="{name}">\n'
            f"    <h2><code>{name}</code></h2>\n"
            f"    <p>{html.escape(purpose)}</p>\n"
            f'    <div class="script-links">'
            f'<a href="{blob}">current version on GitHub</a>'
            f'<a href="{raw}">raw</a>'
            f"<span>shown as of commit {commit}</span></div>\n"
            f'    <pre class="source"><code>{html.escape(source)}</code></pre>\n'
            f"  </section>\n"
        )
    index = "\n".join(
        f'    <li><a href="#{name}"><code>{name}</code></a> — {html.escape(purpose)}</li>'
        for name, purpose in SCRIPTS
    )
    intro = (
        "<section><p>Every script below is the one the deployment actually runs, copied "
        "from the repository at the commit named in each heading. The link above each "
        "goes to the current file, which may be newer than what is shown here.</p>"
        "<p>They are written to be adapted. Every tunable is an environment variable "
        "with a prefixed name and a default — project, region, zone, instance type, image "
        "tag, memory — and nothing in them names a specific account, key or address. "
        "Secrets are read from files the scripts themselves write, outside any repository, "
        "and are never printed. A run against a fresh account creates what is missing and "
        "leaves alone what exists.</p>"
        "<p>The decisions behind each script — why the memory limit needs a unit, why an "
        "update re-sends every variable, why the Instance sits behind a security group "
        "that drops inbound — are in the header comment of each file and, at length, in "
        f'<a href="{GITHUB}/blob/main/docs/DEPLOYMENT_SCALEWAY.md">the deployment guide</a>.</p>'
        f"<ul>\n{index}\n  </ul></section>\n"
    )
    return page(
        "The scripts",
        "<span>Source</span><span>Scaleway fr-par</span><span>Idempotent</span>",
        "The deployment, as code: seven files that stand the stack up from nothing, verify it, and take it down again.",
        intro + "".join(sections),
    )


def main() -> int:
    outputs = {"log.html": build_log(), "deploy.html": build_deploy()}
    if "--check" in sys.argv:
        stale = [
            n for n, content in outputs.items()
            if not (HERE / n).exists()
            or _strip_stamp((HERE / n).read_text(encoding="utf-8")) != _strip_stamp(content)
        ]
        if stale:
            print("stale:", ", ".join(stale), "— run scripts/scaleway/landing/build.py")
            return 1
        print("landing pages are current")
        return 0
    for name, content in outputs.items():
        (HERE / name).write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote {name} ({len(content):,} bytes)")
    return 0


def _strip_stamp(text: str) -> str:
    """The footer names the commit and the day; a check must not fail on those alone."""
    text = re.sub(r"at commit \S+ on \d{4}-\d{2}-\d{2}", "", text)
    return re.sub(r"shown as of commit \S+", "", text)


if __name__ == "__main__":
    sys.exit(main())
