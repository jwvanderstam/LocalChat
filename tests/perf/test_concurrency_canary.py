"""PERF-2 — the event loop stays answerable while SSE streams are in flight.

PERF-1's defect was sync retrieval called inline from an async handler, so one
slow query stalled every other request. It survived for months because nothing
measured behaviour with more than one client, and because the metric everyone
reaches for cannot see it: time-to-first-token is dominated by the queue at the
model, and three runs of one build spread wider than the fix did.

The canary can see it. A `/api/health` probe should answer in single-digit
milliseconds and has nowhere to hide — if the loop is held, it waits too. Across
PERF-1 its worst case moved 848ms -> 305ms while p50/p95 TTFT barely moved.

This drives the committed benchmark rather than reimplementing it, so the thing
gating CI is the same code the ticket's numbers came from.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

from tests.e2e.conftest import ADMIN_PASSWORD, ADMIN_USERNAME

pytestmark = [pytest.mark.slow, pytest.mark.db]

# `scripts/` is not a package, so the benchmark is loaded by path. It must be
# registered in sys.modules before exec: @dataclass resolves its own module
# through sys.modules and raises on a module that is not there.
_SPEC = importlib.util.spec_from_file_location(
    "bench_concurrency",
    Path(__file__).resolve().parents[2] / "scripts" / "bench_concurrency.py",
)
assert _SPEC
assert _SPEC.loader
bench = importlib.util.module_from_spec(_SPEC)
sys.modules["bench_concurrency"] = bench
_SPEC.loader.exec_module(bench)

#: Set from ten observed runs on GitHub runners, not from a guess. Worst probe
#: per run: 201, 219, 237, 241, 249, 262, 271, 278, 287, 293 ms — a spread of
#: only 1.5x between best and worst, so the distribution is well behaved and a
#: threshold is meaningful rather than a coin toss.
#:
#: 1000ms is 3.4x the worst of those, which leaves room for a noisy neighbour
#: while still discriminating: PERF-1's pre-fix worst case was 848ms locally,
#: and this runner sits around 1.6-1.9x local, so the regression this exists to
#: catch would land near 1.4-1.6s. Healthy runs are ~250ms; a held loop is
#: seconds. The gap between them is where this number belongs.
#:
#: Raise it only with evidence of a legitimately slower runner, never to make a
#: red run go away — that is how a budget stops meaning anything.
CANARY_CEILING_MS = 1_000

CLIENTS = 10
#: Sized so the run outlasts the canary's 100ms poll by a wide margin. The first
#: version used 10 requests: against a stubbed model the whole load finished inside
#: a second and the canary collected *one* probe, which would have let the gate pass
#: on a sample of one. MIN_PROBES below is the guard that makes that failure loud
#: rather than green if the timing ever shifts again.
#:
#: This also needs `RATELIMIT_CHAT` raised (see conftest): at the 10-per-minute
#: default, 190 of 200 requests came back 429 without ever reaching the loop.
REQUESTS = 600

#: Below this the run was too short to have measured a worst case.
MIN_PROBES = 15


def _session_cookie(base_url: str) -> dict[str, str]:
    """Sign in over HTTP and return the cookie header the benchmark should send."""
    response = httpx.post(
        f"{base_url}/api/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        timeout=30.0,
    )
    assert response.status_code == 200, f"login failed: {response.status_code} {response.text}"
    token = response.cookies.get("localchat_session")
    assert token, "login succeeded but set no session cookie"
    return {"Cookie": f"localchat_session={token}"}


def _drive(base_url: str, headers: dict[str, str]) -> tuple[list, list[float]]:
    """Run the load and the canary together, as the script's main() does."""
    args = argparse.Namespace(
        url=base_url, key=None, clients=CLIENTS, requests=REQUESTS, timeout=180.0,
    )
    canary: list[float] = []

    async def _both() -> list:
        stop = asyncio.Event()
        watcher = asyncio.create_task(bench._canary(base_url.rstrip("/"), stop, canary))
        try:
            return await bench._run(args, headers)
        finally:
            stop.set()
            await watcher

    return asyncio.run(_both()), canary


def test_the_event_loop_stays_answerable_under_concurrent_sse_load(live_server: str) -> None:
    headers = _session_cookie(live_server)

    samples, canary = _drive(live_server, headers)

    # Printed before any assertion: a perf test that fails without showing its
    # measurements makes the next person re-run it to learn anything.
    succeeded = [s for s in samples if s.ok]
    statuses: dict[object, int] = {}
    for sample in samples:
        key = sample.status if sample.error is None else f"{sample.status}:{sample.error[:40]}"
        statuses[key] = statuses.get(key, 0) + 1
    print(f"\n  streams   {len(succeeded)}/{len(samples)} ok   statuses {statuses}")
    if canary:
        print(f"  canary    {len(canary)} probes   "
              f"p50 {bench._percentile(canary, 50) * 1000:.0f}ms   "
              f"p95 {bench._percentile(canary, 95) * 1000:.0f}ms   "
              f"max {max(canary) * 1000:.0f}ms")
    else:
        print("  canary    no probes")

    assert succeeded, "no chat request completed, so the canary measured an idle server"
    assert len(canary) >= MIN_PROBES, (
        f"only {len(canary)} canary probe(s) — the load finished too fast to have "
        f"measured a worst case; raise REQUESTS"
    )

    breach = bench.canary_verdict(canary, CANARY_CEILING_MS)
    assert breach is None, breach
