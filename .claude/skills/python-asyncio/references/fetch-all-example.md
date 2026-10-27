# Worked example: fetch 20k URLs (full code and lab harness)

Companion to `python-asyncio` section 12. The script below is the exact file that was run in the lab
(Python 3.14, httpx 0.28.1, tenacity 9.2): `mypy --strict` clean, ruff `ASYNC,RUF,B,F,UP,SIM` clean,
silent under `PYTHONDEVMODE=1`, exit code 130 with a valid partial file on SIGINT.

## fetch_all.py

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx>=0.28", "tenacity>=9"]
# ///
"""Fetch many URLs with bounded concurrency; results stream to a JSONL file."""
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_random_exponential

CONCURRENCY = 64
BATCH = 500


def retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)  # connect/read timeouts, resets


async def fetch(client: httpx.AsyncClient, sem: asyncio.Semaphore, url: str) -> dict[str, object]:
    async for attempt in AsyncRetrying(
        retry=retry_if_exception(retryable),
        stop=stop_after_attempt(4),
        wait=wait_random_exponential(multiplier=0.5, max=8),  # full jitter, sleeps outside the semaphore
        reraise=True,
    ):
        with attempt:
            async with sem:  # bound in-flight requests, not sleeping retries
                r = await client.get(url)
            r.raise_for_status()
            return {"url": url, "status": r.status_code, "bytes": len(r.content)}
    raise AssertionError("unreachable")


async def fetch_one(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                    out: asyncio.Queue[dict[str, object]], url: str) -> None:
    try:
        row = await fetch(client, sem, url)
    except httpx.HTTPError as e:  # final failure is data, not a crash of the whole run
        row = {"url": url, "error": type(e).__name__}
    await out.put(row)  # blocks when the writer falls behind: backpressure


async def writer(out: asyncio.Queue[dict[str, object]], path: Path) -> int:
    n, batch = 0, []
    with path.open("a", encoding="utf-8") as f:
        try:
            while True:
                try:
                    batch.append(json.dumps(await out.get()) + "\n")
                except asyncio.QueueShutDown:
                    break
                if len(batch) >= BATCH:
                    await asyncio.to_thread(f.writelines, batch)
                    n, batch = n + len(batch), []
        finally:  # runs on normal end, error and cancellation
            while not out.empty():
                batch.append(json.dumps(out.get_nowait()) + "\n")
            f.writelines(batch)  # synchronous on purpose: no await inside cleanup
            n += len(batch)
    return n


async def main(urls: list[str], path: Path) -> int:
    sem = asyncio.Semaphore(CONCURRENCY)
    out: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=2 * BATCH)
    limits = httpx.Limits(max_connections=CONCURRENCY, max_keepalive_connections=CONCURRENCY)
    timeout = httpx.Timeout(10.0, connect=3.0)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client, asyncio.TaskGroup() as tg:
        w = tg.create_task(writer(out, path))
        async with asyncio.TaskGroup() as fetchers:
            for i, url in enumerate(urls):
                fetchers.create_task(fetch_one(client, sem, out, url))
                if i % 500 == 499:
                    await asyncio.sleep(0)  # yield so one loop step never creates 20k tasks
        out.shutdown()  # writer drains what is queued, then sees QueueShutDown
    return w.result()


if __name__ == "__main__":
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    urls = src.read_text().split()
    t0 = time.perf_counter()
    try:
        written = asyncio.run(main(urls, dst))
    except KeyboardInterrupt:  # asyncio.run cancelled main() and cleaned up first
        print("interrupted; partial results kept in", dst, file=sys.stderr)
        sys.exit(130)
    print(f"{written} rows in {time.perf_counter() - t0:.1f}s", file=sys.stderr)
```

Design notes:

| Choice | Reason |
|---|---|
| semaphore inside each retry attempt | backoff sleeps do not occupy one of the 64 slots |
| retry only 5xx and `TransportError` | 4xx is a permanent answer; retrying it wastes the origin's capacity |
| `wait_random_exponential(multiplier=0.5, max=8)` | full jitter spreads retries so they do not arrive in waves |
| final failure becomes a row | one dead URL must not cancel 19,999 siblings through the TaskGroup |
| bounded output queue (1,000) | if the disk stalls, fetchers block on `put` instead of buffering everything in memory |
| batched `to_thread(f.writelines, batch)` | file writes leave the loop; one thread hop per 500 rows, not per row |
| synchronous flush in `finally` | cleanup after cancellation must not await anything long |
| `await asyncio.sleep(0)` every 500 creations | keeps each loop step short; debug mode otherwise logs the creation loop as a slow callback |
| `out.shutdown()` after the fetchers group | the writer drains what is queued, then exits on `QueueShutDown` |
| `KeyboardInterrupt` caught only around `asyncio.run` | `asyncio.run` cancels `main()` first, so all cleanup has already run |

## Local test server (aserver.py)

Single-threaded asyncio HTTP/1.1 keep-alive server: latency `LAT * uniform(0.5, 1.5)`, 2% 503s.

```python
import asyncio, random, sys
LAT = float(sys.argv[2]); FAIL = float(sys.argv[3]) if len(sys.argv) > 3 else 0.02
async def handle(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
    try:
        while True:
            head = await r.readuntil(b"\r\n\r\n")
            await asyncio.sleep(LAT * random.uniform(0.5, 1.5))
            code = b"503 Service Unavailable" if random.random() < FAIL else b"200 OK"
            body = b"x" * 512
            w.write(b"HTTP/1.1 " + code + b"\r\nContent-Length: 512\r\n\r\n" + body)
            await w.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        w.close()
async def main() -> None:
    srv = await asyncio.start_server(handle, "127.0.0.1", int(sys.argv[1]), backlog=1024)
    async with srv:
        await srv.serve_forever()
asyncio.run(main())
```

```bash
uv run --no-project --python 3.13 python aserver.py 8766 0.05 &     # port, mean latency (s)
python3 -c "print('\n'.join(f'http://127.0.0.1:8766/item/{i}' for i in range(3000)))" > urls.txt
PYTHONDEVMODE=1 uv run --script fetch_all.py urls.txt out.jsonl
```

## SIGINT harness (sigint_harness.py)

Sends SIGINT to the interpreter itself (not the `uv` wrapper, whose PID differs), then checks the
exit code and prints the tail of stderr. Pass the script environment's Python
(`ls ~/.cache/uv/environments-v2/fetch-all-*/bin/python`).

```python
import os, signal, subprocess, sys, time
env = dict(os.environ, PYTHONDEVMODE="1")
py = sys.argv[1]
p = subprocess.Popen([py, "fetch_all.py", "urls.txt", "part.jsonl"], stderr=subprocess.PIPE, text=True, env=env)
time.sleep(4)
p.send_signal(signal.SIGINT)
err = p.communicate(timeout=30)[1]
lines = [l[:200] for l in err.splitlines() if "took 0." not in l]
print("exit", p.returncode)
print("\n".join(lines[-15:]))
```

Check the partial file afterwards:
`python3 -c "import json; print(sum(1 for l in open('part.jsonl') if json.loads(l)))"`
(any truncated line raises).

## Concurrency sweep

Measure before choosing the semaphore size. Run against the real origin (with permission) or a
staging copy; record throughput and p50/p99 latency per level:

```python
import asyncio, time, httpx

async def sweep(url: str, levels: tuple[int, ...] = (8, 16, 32, 64), per_level: int = 10) -> None:
    for conc in levels:
        sem = asyncio.Semaphore(conc)
        lat: list[float] = []
        limits = httpx.Limits(max_connections=conc, max_keepalive_connections=conc)
        async with httpx.AsyncClient(limits=limits) as client:
            async def one() -> None:
                async with sem:
                    t = time.perf_counter()
                    await client.get(url)
                    lat.append(time.perf_counter() - t)
            n = conc * per_level
            t0 = time.perf_counter()
            async with asyncio.TaskGroup() as tg:
                for _ in range(n):
                    tg.create_task(one())
            dt = time.perf_counter() - t0
        lat.sort()
        print(f"{conc:>3} {n / dt:7.0f} req/s  p50 {lat[len(lat) // 2]:.3f}  p99 {lat[int(len(lat) * 0.99)]:.3f}")
```

Lab result against the local server above (50 ms mean latency), httpx 0.28.1 on macOS:

| Concurrency | req/s | p50 (s) | p99 (s) |
|---|---|---|---|
| 40 | 695 | 0.050 | 0.081 |
| 48 | 648 | 0.055 | 0.241 |
| 56 | 178 | 0.183 | 1.292 |
| 64 | 160 | 0.229 | 1.826 |

aiohttp with 64 connections reached about 1,170 req/s against the same server, so the knee was in
the client stack, not the origin. Reading: pick the level just before p99 jumps; if throughput stops
rising while the origin is idle, benchmark another client before raising concurrency.

## Interpreting the production numbers with Little's law

| Quantity | Value |
|---|---|
| URLs | 20,000 |
| sequential mean latency | 0.123 s, so 41 min |
| concurrent wall time | 210 s, so throughput 95 req/s |
| in flight (semaphore) | L = 64 |
| implied time in flight | W = L / lambda = 64 / 95 = 0.67 s |

W is 5.5x the unloaded latency: requests queue at the origin. More concurrency would add queueing
only; fewer slots (the sweep's plateau point) give the same throughput with less load on the origin.
