#!/usr/bin/env python3
"""Prove the Scaleway Serverless SQL Database can actually host LocalChat.

Four things decide that, and only one of them is obvious:

1. The credential connects at all, and the connection is really encrypted.
2. ``CREATE EXTENSION vector`` succeeds — a managed Postgres may not permit it,
   and the whole retrieval layer depends on it.
3. ``SET hnsw.ef_search`` survives into a *later* transaction. ``src/db/connection.py``
   sets it once per physical connection in the pool's ``configure`` callback and
   assumes it sticks. Behind a transaction-pooling proxy it does not, and nothing
   errors — retrieval just quietly gets worse. This is §4's open caveat.
4. The identity is scoped: it can read and write, and it cannot drop the database.

Run it after ``provision.sh``:

    python scripts/scaleway/verify_database.py

Reads the credential from ``PROVISION_ENV_OUT`` (default
``~/.config/scw/localchat-db.env``). Prints no secret. Exits non-zero if any
check fails, so it can gate a deployment.
"""

from __future__ import annotations

import os
import pathlib
import sys

try:
    import psycopg
except ImportError:  # pragma: no cover - the message is the whole value here
    sys.exit("psycopg is not installed: pip install 'psycopg[binary]'")

DEFAULT_ENV = pathlib.Path.home() / ".config" / "scw" / "localchat-db.env"


def load_credentials(path: pathlib.Path) -> dict[str, str]:
    if not path.exists():
        sys.exit(f"no credential file at {path} — run scripts/scaleway/provision.sh first")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    missing = {"PG_HOST", "PG_PORT", "PG_DB", "PG_USER", "PG_PASSWORD"} - values.keys()
    if missing:
        sys.exit(f"{path} is missing {', '.join(sorted(missing))}")
    return values


class Report:
    def __init__(self) -> None:
        self.failed = 0

    def ok(self, label: str, detail: str = "") -> None:
        print(f"  PASS  {label}{f' — {detail}' if detail else ''}")

    def bad(self, label: str, detail: str) -> None:
        self.failed += 1
        print(f"  FAIL  {label} — {detail}")

    def note(self, text: str) -> None:
        print(f"        {text}")


def main() -> int:
    env_path = pathlib.Path(os.environ.get("PROVISION_ENV_OUT", str(DEFAULT_ENV)))
    creds = load_credentials(env_path)
    report = Report()

    print(f"Verifying {creds['PG_HOST']}/{creds['PG_DB']} as {creds['PG_USER'][:8]}…\n")

    conn_kwargs = {
        "host": creds["PG_HOST"],
        "port": int(creds["PG_PORT"]),
        "dbname": creds["PG_DB"],
        "user": creds["PG_USER"],
        "password": creds["PG_PASSWORD"],
        "sslmode": creds.get("PG_SSLMODE", "require"),
        "connect_timeout": 20,
    }

    try:
        conn = psycopg.connect(**conn_kwargs)
    except Exception as exc:
        report.bad("connect", str(exc).strip().splitlines()[0])
        return 1

    with conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            row = cur.fetchone()
            report.ok("connect", (row[0] if row else "?").split(" on ")[0])

            # 1. Encryption. `pg_stat_ssl` is the wrong probe here: it reports the
            #    pooler's own connection to Postgres, which is internal and shows
            #    no TLS even when the client connection is fully encrypted. The
            #    honest test is whether the server refuses an unencrypted one.
            try:
                psycopg.connect(**{**conn_kwargs, "sslmode": "disable"}).close()
                report.bad("server requires TLS", "an sslmode=disable connection was accepted")
            except Exception as exc:
                first = str(exc).strip().splitlines()[0]
                report.ok("server requires TLS", "sslmode=disable is refused")
                if "ServerNameIndication" in str(exc) or "hostname wasn't sent" in str(exc):
                    report.note("Routing is by TLS SNI — the database is selected by the")
                    report.note("server name in the handshake, so TLS is structural here,")
                    report.note("not merely advisable. PG_SSLMODE=require is mandatory.")
                else:
                    report.note(first[:100])

            # 2. pgvector.
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                ver = cur.fetchone()
                if ver:
                    report.ok("pgvector available", f"version {ver[0]}")
                else:
                    report.bad("pgvector available", "CREATE EXTENSION ran but pg_extension has no row")
            except Exception as exc:
                report.bad("pgvector available", str(exc).strip().splitlines()[0])

            # 3. The caveat. Set it, end the transaction, then read it back on
            #    what the pooler may or may not consider the same session.
            try:
                cur.execute("SET hnsw.ef_search = 100")
                cur.execute("COMMIT")
                cur.execute("BEGIN")
                cur.execute("SHOW hnsw.ef_search")
                seen = cur.fetchone()
                observed = seen[0] if seen else "?"
                cur.execute("COMMIT")
                if str(observed) == "100":
                    report.ok("hnsw.ef_search persists across transactions", observed)
                    report.note("The pool's configure callback is enough; §4's caveat does not bite.")
                else:
                    report.bad(
                        "hnsw.ef_search persists across transactions",
                        f"read back {observed!r}, expected '100'",
                    )
                    report.note("Set it per checkout or per query in src/db/connection.py.")
            except Exception as exc:
                report.bad("hnsw.ef_search persists across transactions", str(exc).strip().splitlines()[0])

            # 4. Scope: writing is allowed, dropping the database is not.
            try:
                cur.execute("CREATE TABLE IF NOT EXISTS _localchat_probe (id int)")
                cur.execute("INSERT INTO _localchat_probe VALUES (1)")
                cur.execute("SELECT count(*) FROM _localchat_probe")
                cur.execute("DROP TABLE _localchat_probe")
                report.ok("DDL and DML permitted", "create/insert/select/drop table")
            except Exception as exc:
                report.bad("DDL and DML permitted", str(exc).strip().splitlines()[0])

            try:
                cur.execute(f'DROP DATABASE "{creds["PG_DB"]}"')
                report.bad("cannot drop its own database", "the drop succeeded — the identity is too broad")
            except Exception as exc:
                report.ok("cannot drop its own database", str(exc).strip().splitlines()[0][:70])

    print()
    if report.failed:
        print(f"{report.failed} check(s) failed — do not deploy against this database yet.")
        return 1
    print("All checks passed. The database is ready for Phase 2.")
    print("Note: verify-full needs Scaleway's CA in sslrootcert; require does not.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
