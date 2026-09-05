#!/usr/bin/env python3
"""Phase 3: prove a deployed LocalChat actually works, and gate on the answer.

Every check here was run by hand against the first Scaleway deployment. Three of
them found something the deployment plan had wrong, which is why they are a
script now rather than a checklist someone reads:

* The running version is **not** on ``/api/status`` — that endpoint carries no
  version at all. It is on ``/api/settings/stats``, which is admin-only.
* ``/api/health`` reporting a healthy database was, until it was fixed, an echo
  of a boot-time flag. This asks for a live answer by exercising a route that
  touches the database.
* The document path needs an embedding model. Without one, upload fails cleanly
  and nothing is stored — so "retrieval works without Ollama" is false, and this
  reports that as a skip rather than a pass.

Usage:
    python scripts/scaleway/verify_deployment.py <endpoint>
    python scripts/scaleway/verify_deployment.py <endpoint> --pull-model nomic-embed-text

Reads ADMIN_PASSWORD from the deployment secrets file (``DEPLOY_SECRET_ENV``,
default ``~/.config/scw/localchat-deploy.env``). Prints no secret. Exits
non-zero when a check fails, so it can stand in front of a release.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

DEFAULT_SECRET_ENV = pathlib.Path.home() / ".config" / "scw" / "localchat-deploy.env"
PROBE_NAME = "deployment-probe.md"
CANARY = "quiet-utility-marmoset-4417"
PROBE_BODY = f"""# LocalChat deployment probe

This document exists to prove that ingest and retrieval work on the deployed stack.

The canary phrase is: {CANARY}.

The Serverless SQL Database routes connections by TLS SNI, which is why an
unencrypted connection cannot name the database it wants.
"""


class Report:
    def __init__(self) -> None:
        self.failed = 0
        self.skipped = 0

    def ok(self, label: str, detail: str = "") -> None:
        print(f"  PASS  {label}{f' — {detail}' if detail else ''}")

    def bad(self, label: str, detail: str) -> None:
        self.failed += 1
        print(f"  FAIL  {label} — {detail}")

    def skip(self, label: str, detail: str) -> None:
        self.skipped += 1
        print(f"  SKIP  {label} — {detail}")

    def note(self, text: str) -> None:
        print(f"        {text}")


class Client:
    """The smallest HTTP client that keeps a session cookie."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.cookie: str | None = None

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str | None = None,
        timeout: int = 120,
    ) -> tuple[int, bytes]:
        req = urllib.request.Request(f"{self.base}{path}", data=body, method=method)
        if content_type:
            req.add_header("Content-Type", content_type)
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                set_cookie = resp.headers.get("Set-Cookie")
                if set_cookie:
                    self.cookie = set_cookie.split(";", 1)[0]
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def json(self, method: str, path: str, payload: dict | None = None, timeout: int = 120):
        body = json.dumps(payload).encode() if payload is not None else None
        status, raw = self.request(
            method, path, body, "application/json" if body else None, timeout
        )
        try:
            return status, json.loads(raw)
        except Exception:
            return status, raw.decode("utf-8", "replace")


def load_admin_password() -> str:
    path = pathlib.Path(os.environ.get("DEPLOY_SECRET_ENV", str(DEFAULT_SECRET_ENV)))
    if not path.exists():
        sys.exit(f"no secrets file at {path} — run scripts/scaleway/deploy_container.sh")
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("ADMIN_PASSWORD="):
            return line.split("=", 1)[1].strip()
    sys.exit(f"{path} has no ADMIN_PASSWORD")


def multipart(filename: str, content: str) -> tuple[bytes, str]:
    boundary = "----localchatprobe"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
        "Content-Type: text/markdown\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    return body, f"multipart/form-data; boundary={boundary}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("endpoint", help="https://…functions.fnc.fr-par.scw.cloud")
    parser.add_argument(
        "--pull-model",
        metavar="NAME",
        help="pull this embedding model through the app before testing ingest",
    )
    parser.add_argument(
        "--expect-version", default="3.0.0", help="version the deployed image must report"
    )
    args = parser.parse_args()

    client = Client(args.endpoint)
    report = Report()
    print(f"Verifying {client.base}\n")

    status, health = client.json("GET", "/api/health", timeout=60)
    if status != 200 or not isinstance(health, dict):
        report.bad("health answers", f"HTTP {status}")
        return 1
    checks = health.get("checks", {})
    report.ok("health answers", health.get("status", "?"))
    db_up = checks.get("database", {}).get("healthy")
    (report.ok if db_up else report.bad)("database reachable", checks.get("database", {}).get("status", "?"))
    ollama_up = bool(checks.get("ollama", {}).get("healthy"))
    (report.ok if ollama_up else report.skip)(
        "ollama reachable",
        checks.get("ollama", {}).get("status", "?")
        + ("" if ollama_up else " — ingest and chat cannot work without it"),
    )

    status, _ = client.json(
        "POST", "/api/auth/login", {"username": "admin", "password": load_admin_password()}
    )
    if status != 200:
        report.bad("admin can sign in", f"HTTP {status}")
        return 1
    report.ok("admin can sign in")

    status, stats = client.json("GET", "/api/settings/stats")
    version = (stats or {}).get("system", {}).get("app_version") if isinstance(stats, dict) else None
    if version == args.expect_version:
        report.ok("deployed image is the expected one", f"app_version {version}")
    else:
        report.bad(
            "deployed image is the expected one",
            f"reports {version!r}, expected {args.expect_version!r}",
        )

    if args.pull_model and ollama_up:
        print(f"  ....  pulling {args.pull_model} (minutes, streams progress)")
        status, _ = client.request(
            "POST",
            "/api/models/pull",
            json.dumps({"model": args.pull_model}).encode(),
            "application/json",
            timeout=1800,
        )
        (report.ok if status == 200 else report.bad)(
            f"pulled {args.pull_model}", f"HTTP {status}"
        )

    if not ollama_up:
        report.skip("document ingest", "no embedding model reachable")
        report.skip("semantic retrieval", "nothing can be ingested")
    else:
        body, content_type = multipart(PROBE_NAME, PROBE_BODY)
        status, raw = client.request(
            "POST", "/api/documents/upload", body, content_type, timeout=900
        )
        text = raw.decode("utf-8", "replace")
        if status == 200 and '"success": true' in text:
            report.ok("document ingest", PROBE_NAME)
        else:
            detail = next(
                (line for line in text.splitlines() if "message" in line), f"HTTP {status}"
            )
            report.bad("document ingest", detail[:160])

        # Semantic, not lexical: the query shares no word with the canary, so a
        # hit can only come from the embedding.
        status, found = client.json(
            "POST", "/api/documents/test", {"query": "which animal is named in this document?"}
        )
        chunks = (
            (found or {}).get("results", {}).get("semantic_only", {}).get("chunks", [])
            if isinstance(found, dict)
            else []
        )
        if chunks and CANARY in json.dumps(chunks):
            report.ok("semantic retrieval", f"similarity {chunks[0].get('similarity')}")
            report.note("The query shares no words with the canary, so this is the vector arm.")
        else:
            report.bad("semantic retrieval", "the probe document did not come back")

    print()
    if report.failed:
        print(f"{report.failed} check(s) failed — this deployment is not good.")
        return 1
    if report.skipped:
        print(f"All checks passed, {report.skipped} skipped. Phase 3 is incomplete "
              "until an embedding model is reachable (Phase 4).")
        return 0
    print("All checks passed. Phase 3 is complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
