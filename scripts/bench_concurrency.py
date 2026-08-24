"""PERF-2 — measure /api/chat under concurrent SSE load.

PERF-1's defect (sync retrieval inline on the event loop, so one slow query stalled
every other request) survived for months because nothing ever measured behaviour with
more than one client. A single-user stopwatch cannot see it: the request that blocks
the loop is the one that finishes on time.

Reports p50/p95 time-to-first-token and total stream time. Run it against a seeded
corpus before and after a change and record both in docs/PRODUCTION_PLAN.md.

    python scripts/bench_concurrency.py --url http://localhost:5000 --key lcw_... \
        --clients 10 --requests 20

Exits non-zero if --max-p95-ttft or --max-canary-ms is given and exceeded, so it can
gate a CI job.

Prefer --max-canary-ms for that gate. Time-to-first-token measures the queue at the
model, not the application: three runs of the same build spread wider than the change
PERF-1 made, so a TTFT budget is noise. The canary is a request that should take
milliseconds and cannot hide behind the model — its worst case moved 848ms -> 305ms
across PERF-1, and it stays meaningful when generation is stubbed, which is what makes
it the metric a deterministic CI environment can actually gate on.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass

import httpx

DEFAULT_PROMPTS = [
    "What does the documentation say about workspaces?",
    "Summarise the retrieval pipeline.",
    "How is authentication handled?",
    "Which database extensions are required?",
    "What happens when a document is deleted?",
]


@dataclass
class Sample:
    ttft: float | None
    total: float
    status: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.error is None and self.ttft is not None


async def _one_request(client: httpx.AsyncClient, url: str, headers: dict, prompt: str) -> Sample:
    started = time.perf_counter()
    ttft: float | None = None
    body = {"message": prompt, "use_rag": True}
    try:
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code != 200:
                await resp.aread()
                return Sample(None, time.perf_counter() - started, resp.status_code)
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                # Time-to-first-*token*: the done frame and the plan frame carry no
                # content, and counting either would flatter a stalled stream.
                payload = json.loads(line[6:])
                if payload.get("content") and ttft is None:
                    ttft = time.perf_counter() - started
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        return Sample(ttft, time.perf_counter() - started, 0, str(exc))
    return Sample(ttft, time.perf_counter() - started, 200)


async def _canary(url: str, stop: asyncio.Event, out: list[float]) -> None:
    """Poll a cheap endpoint while the load runs.

    This is the measurement that actually sees a blocked event loop. Chat latency does
    not: with several clients the LLM serialises anyway, so time-to-first-token is
    dominated by the queue at the model and a stalled loop hides inside it. A request
    that should take milliseconds cannot hide — if the loop is held, it waits too.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        while not stop.is_set():
            started = time.perf_counter()
            try:
                await client.get(url + "/api/health")
                out.append(time.perf_counter() - started)
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)


async def _run(args: argparse.Namespace, headers: dict[str, str] | None = None) -> list[Sample]:
    url = args.url.rstrip("/") + "/api/chat"
    # Explicit headers let a caller authenticate with a session cookie instead of a
    # workspace key — which is what the CI harness has, since it signs in as a user.
    if headers is None:
        headers = {"Authorization": f"Bearer {args.key}"} if args.key else {}
    limits = httpx.Limits(max_connections=args.clients * 2)
    semaphore = asyncio.Semaphore(args.clients)

    async with httpx.AsyncClient(timeout=args.timeout, limits=limits) as client:
        async def _guarded(i: int) -> Sample:
            async with semaphore:
                return await _one_request(client, url, headers, DEFAULT_PROMPTS[i % len(DEFAULT_PROMPTS)])

        return await asyncio.gather(*(_guarded(i) for i in range(args.requests)))


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    # Nearest-rank: with 20 samples the p95 is a real observation, not an interpolation
    # between two, which is what you want when reporting a worst-case budget.
    index = min(len(ordered) - 1, max(0, round(pct / 100 * len(ordered)) - 1))
    return ordered[index]


def canary_verdict(canary: list[float], budget_ms: float | None) -> str | None:
    """Return a failure message when the canary breaches *budget_ms*, else ``None``.

    An empty sample list is a failure, not a pass: a canary that never ran measured
    nothing, and silence must not read as a green gate.
    """
    if budget_ms is None:
        return None
    if not canary:
        return "FAIL: no canary probes collected — the event loop was never measured"
    worst_ms = max(canary) * 1000
    if worst_ms > budget_ms:
        return f"FAIL: canary max {worst_ms:.0f}ms exceeds budget {budget_ms:.0f}ms"
    return None


def _report(samples: list[Sample], clients: int) -> tuple[float, float]:
    ok = [s for s in samples if s.ok]
    failed = [s for s in samples if not s.ok]
    ttfts = [s.ttft for s in ok if s.ttft is not None]
    totals = [s.total for s in ok]

    print(f"\n{len(ok)}/{len(samples)} succeeded at {clients} concurrent clients")
    if failed:
        shown = {(s.status, s.error) for s in failed}
        print(f"  failures: {sorted(shown, key=str)[:3]}")
    if not ok:
        return float("nan"), float("nan")

    p95_ttft = _percentile(ttfts, 95)
    print(f"  time-to-first-token   p50 {_percentile(ttfts, 50):6.2f}s   p95 {p95_ttft:6.2f}s")
    print(f"  total stream time     p50 {_percentile(totals, 50):6.2f}s   "
          f"p95 {_percentile(totals, 95):6.2f}s")
    print(f"  slowest total         {max(totals):6.2f}s   mean {statistics.mean(totals):6.2f}s")
    return p95_ttft, _percentile(totals, 95)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:5000")
    parser.add_argument("--key", help="workspace API key (lcw_...)")
    parser.add_argument("--clients", type=int, default=10, help="concurrent in flight")
    parser.add_argument("--requests", type=int, default=20, help="total requests")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-p95-ttft", type=float, help="fail if p95 TTFT exceeds this")
    parser.add_argument("--max-canary-ms", type=float,
                        help="fail if the slowest /api/health probe exceeds this (ms). "
                             "The gate to use in CI — see the module docstring.")
    args = parser.parse_args()

    canary: list[float] = []

    async def _both() -> list[Sample]:
        stop = asyncio.Event()
        watcher = asyncio.create_task(_canary(args.url.rstrip("/"), stop, canary))
        try:
            return await _run(args)
        finally:
            stop.set()
            await watcher

    samples = asyncio.run(_both())
    p95_ttft, _ = _report(samples, args.clients)
    if canary:
        print(f"  loop responsiveness   p50 {_percentile(canary, 50) * 1000:6.0f}ms  "
              f"p95 {_percentile(canary, 95) * 1000:6.0f}ms  max {max(canary) * 1000:6.0f}ms"
              f"   ({len(canary)} probes)")

    if not [s for s in samples if s.ok]:
        print("\nNo successful requests — check the URL, the key and that a model is active.")
        return 1
    if args.max_p95_ttft is not None and p95_ttft > args.max_p95_ttft:
        print(f"\nFAIL: p95 TTFT {p95_ttft:.2f}s exceeds budget {args.max_p95_ttft:.2f}s")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
