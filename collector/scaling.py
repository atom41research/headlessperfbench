"""Multi-worker process pool for scaling tests.

Runs N browser worker processes within a single container, each pulling URLs
from a shared queue.  The main process samples container cgroup metrics on a
continuous timeline while workers are active.
"""

import asyncio
import json
import multiprocessing
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
)

from . import config
from .collector import (
    PageMetrics,
    _in_container,
    _read_cgroup_cpu_usec,
    _read_cgroup_int,
    _read_cgroup_memory_stat,
    CGROUP_MEMORY_CURRENT,
    collect_page_data,
)
from .parser import RankedURL

console = Console()

_MODE_TIMEOUT_S = 60


# ── Container cgroup timeline sampler ────────────────────────────────────


@dataclass
class CgroupSample:
    t: float  # seconds since start
    memory_current_mb: float
    active_memory_mb: float
    cpu_usage_usec: int
    cpu_pct: float


def _cgroup_sampler_thread(
    stop_event: threading.Event,
    interval: float,
    samples: list[dict],
) -> None:
    """Sample cgroup metrics every *interval* seconds until *stop_event* is set."""
    if not _in_container():
        return

    t0 = time.monotonic()
    prev_cpu_usec = _read_cgroup_cpu_usec()
    prev_time = t0

    while not stop_event.is_set():
        now = time.monotonic()
        dt = now - prev_time

        mem_bytes = _read_cgroup_int(CGROUP_MEMORY_CURRENT)
        mem_mb = mem_bytes / (1024 * 1024) if mem_bytes >= 0 else 0.0

        mem_stat = _read_cgroup_memory_stat()
        anon = mem_stat.get("anon", 0)
        kernel = mem_stat.get("kernel", 0)
        active_mb = (anon + kernel) / (1024 * 1024)

        cpu_usec = _read_cgroup_cpu_usec()
        cpu_pct = 0.0
        if prev_cpu_usec >= 0 and cpu_usec >= 0 and dt > 0:
            cpu_pct = ((cpu_usec - prev_cpu_usec) / (dt * 1_000_000)) * 100
        prev_cpu_usec = cpu_usec
        prev_time = now

        samples.append({
            "t": round(now - t0, 3),
            "memory_current_mb": round(mem_mb, 1),
            "active_memory_mb": round(active_mb, 1),
            "cpu_usage_usec": cpu_usec,
            "cpu_pct": round(cpu_pct, 1),
        })

        stop_event.wait(timeout=interval)


# ── Worker process ───────────────────────────────────────────────────────


def _worker_loop(
    work_queue: multiprocessing.Queue,
    result_queue: multiprocessing.Queue,
    worker_id: int,
    mode: str,
    output_dir_str: str,
) -> None:
    """Long-running worker process.  Starts Playwright once, processes URLs
    from *work_queue* until it receives a ``None`` sentinel."""

    output_dir = Path(output_dir_str)

    async def _run() -> None:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            while True:
                item = work_queue.get()
                if item is None:
                    break

                url, host, rank = item["url"], item["host"], item["rank"]
                host_slug = host.replace(".", "_")
                wall_start = time.monotonic()

                try:
                    metrics = await asyncio.wait_for(
                        collect_page_data(
                            pw, url, mode, output_dir, host_slug, rank=rank,
                        ),
                        timeout=_MODE_TIMEOUT_S,
                    )
                    result_queue.put({
                        "worker_id": worker_id,
                        "host": host,
                        "rank": rank,
                        mode: asdict(metrics),
                        "wall_start": wall_start,
                        "wall_end": time.monotonic(),
                        "error": None,
                    })
                except asyncio.TimeoutError:
                    result_queue.put({
                        "worker_id": worker_id,
                        "host": host,
                        "rank": rank,
                        mode: asdict(PageMetrics(
                            url=url, mode=mode,
                            error=f"Timed out after {_MODE_TIMEOUT_S}s",
                        )),
                        "wall_start": wall_start,
                        "wall_end": time.monotonic(),
                        "error": f"timeout ({_MODE_TIMEOUT_S}s)",
                    })
                except Exception as e:
                    result_queue.put({
                        "worker_id": worker_id,
                        "host": host,
                        "rank": rank,
                        mode: asdict(PageMetrics(
                            url=url, mode=mode, error=str(e)[:200],
                        )),
                        "wall_start": wall_start,
                        "wall_end": time.monotonic(),
                        "error": str(e)[:200],
                    })

    try:
        asyncio.run(_run())
    except Exception as e:
        # Fatal: Playwright or event loop failed entirely
        result_queue.put({
            "worker_id": worker_id,
            "host": "__fatal__",
            "rank": -1,
            "error": f"worker {worker_id} fatal: {e!s:.200}",
        })


# ── Scaling result ───────────────────────────────────────────────────────


@dataclass
class ScalingResult:
    mode: str
    num_workers: int
    wall_time_s: float = 0.0
    start_time_iso: str = ""
    end_time_iso: str = ""
    urls_total: int = 0
    urls_ok: int = 0
    urls_failed: int = 0
    failed_urls: list[str] = field(default_factory=list)
    per_url_metrics: list[dict] = field(default_factory=list)
    container_timeline: list[dict] = field(default_factory=list)
    per_worker_stats: dict[int, dict] = field(default_factory=dict)


# ── Main orchestrator ────────────────────────────────────────────────────


def run_scaling_test(
    mode: str,
    num_workers: int,
    urls: list[RankedURL],
    output_dir: Path,
) -> ScalingResult:
    """Run *num_workers* concurrent browser processes for *mode*."""

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "screenshots").mkdir(exist_ok=True)
    (output_dir / "har").mkdir(exist_ok=True)

    mode_cfg = config.MODE_CONFIG.get(mode)
    if not mode_cfg:
        console.print(f"[red]Unknown mode: {mode}[/red]")
        return ScalingResult(mode=mode, num_workers=num_workers)

    console.print(f"\n[bold]Scaling Test: {mode} — {num_workers} workers[/bold]")
    console.print(f"URLs: {len(urls)}")
    console.print(f"Output: {output_dir}\n")

    # Queues
    work_queue: multiprocessing.Queue = multiprocessing.Queue()
    result_queue: multiprocessing.Queue = multiprocessing.Queue()

    # Fill work queue
    for ru in urls:
        work_queue.put({"url": ru.url, "host": ru.host, "rank": ru.rank})
    for _ in range(num_workers):
        work_queue.put(None)  # sentinels

    # Start cgroup sampler
    cgroup_samples: list[dict] = []
    cgroup_stop = threading.Event()
    sampler = threading.Thread(
        target=_cgroup_sampler_thread,
        args=(cgroup_stop, 0.5, cgroup_samples),
        daemon=True,
    )

    # Start workers
    start_iso = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    sampler.start()

    workers: list[multiprocessing.Process] = []
    for wid in range(num_workers):
        p = multiprocessing.Process(
            target=_worker_loop,
            args=(work_queue, result_queue, wid, mode, str(output_dir)),
            name=f"worker-{wid}",
        )
        p.start()
        workers.append(p)

    # Collect results
    collected: list[dict] = []
    expected = len(urls)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"[{mode}] {num_workers}w", total=expected,
        )

        while len(collected) < expected:
            # Check if all workers are dead but results remain
            all_dead = not any(p.is_alive() for p in workers)

            try:
                result = result_queue.get(timeout=2)
            except Exception:
                if all_dead:
                    break
                continue

            # Skip fatal markers from the count
            if result.get("host") == "__fatal__":
                console.print(
                    f"[red]{result.get('error', 'unknown fatal error')}[/red]"
                )
                continue

            collected.append(result)
            host = result.get("host", "?")
            wid = result.get("worker_id", "?")
            progress.update(
                task,
                description=f"[{mode}] w{wid}: {host}",
            )
            progress.advance(task)

    # Wait for workers to finish
    for p in workers:
        p.join(timeout=10)
        if p.is_alive():
            p.terminate()
            p.join(timeout=5)

    wall_time = time.monotonic() - t0
    end_iso = datetime.now(timezone.utc).isoformat()

    # Stop cgroup sampler
    cgroup_stop.set()
    sampler.join(timeout=2)

    # Build per-worker stats
    worker_stats: dict[int, dict] = {}
    for r in collected:
        wid = r.get("worker_id", -1)
        if wid not in worker_stats:
            worker_stats[wid] = {
                "urls_processed": 0,
                "urls_failed": 0,
                "first_url_wall": None,
                "last_url_wall": None,
            }
        ws = worker_stats[wid]
        ws["urls_processed"] += 1
        if r.get("error"):
            ws["urls_failed"] += 1

        wall_end = r.get("wall_end")
        wall_start = r.get("wall_start")
        if wall_start is not None:
            rel_start = wall_start - t0
            rel_end = wall_end - t0 if wall_end else rel_start
            if ws["first_url_wall"] is None or rel_start < ws["first_url_wall"]:
                ws["first_url_wall"] = round(rel_start, 2)
            if ws["last_url_wall"] is None or rel_end > ws["last_url_wall"]:
                ws["last_url_wall"] = round(rel_end, 2)

    # Compute total time per worker
    for ws in worker_stats.values():
        first = ws.get("first_url_wall") or 0.0
        last = ws.get("last_url_wall") or 0.0
        ws["total_wall_time_s"] = round(last - first, 2)

    # Build per-URL metrics list (existing format + worker_id)
    per_url: list[dict] = []
    failed_urls: list[str] = []
    for r in collected:
        entry = {
            "host": r["host"],
            "rank": r["rank"],
            "worker_id": r.get("worker_id", -1),
        }
        if mode in r:
            entry[mode] = r[mode]
        per_url.append(entry)
        if r.get("error"):
            url_val = r.get(mode, {}).get("url", r["host"])
            failed_urls.append(url_val)

    urls_ok = sum(1 for r in collected if not r.get("error"))
    urls_failed = sum(1 for r in collected if r.get("error"))

    result = ScalingResult(
        mode=mode,
        num_workers=num_workers,
        wall_time_s=round(wall_time, 2),
        start_time_iso=start_iso,
        end_time_iso=end_iso,
        urls_total=len(urls),
        urls_ok=urls_ok,
        urls_failed=urls_failed,
        failed_urls=failed_urls,
        per_url_metrics=per_url,
        container_timeline=cgroup_samples,
        per_worker_stats=worker_stats,
    )

    console.print(f"\n[bold green]Done:[/bold green] {mode} {num_workers}w — "
                  f"{wall_time:.1f}s, {urls_ok}/{len(urls)} ok")
    return result


# ── Output ───────────────────────────────────────────────────────────────


def save_scaling_output(result: ScalingResult, output_dir: Path) -> None:
    """Save raw metrics and scaling metadata to *output_dir*."""

    # raw_metrics_{mode}.json — backward compatible with generate_stats.py
    raw_path = output_dir / f"raw_metrics_{result.mode}.json"
    raw_path.write_text(json.dumps(result.per_url_metrics, indent=2, default=str))
    console.print(f"  Saved {raw_path}")

    # scaling_meta.json — scaling-specific metadata
    meta = {
        "mode": result.mode,
        "num_workers": result.num_workers,
        "wall_time_s": result.wall_time_s,
        "start_time_iso": result.start_time_iso,
        "end_time_iso": result.end_time_iso,
        "urls_total": result.urls_total,
        "urls_ok": result.urls_ok,
        "urls_failed": result.urls_failed,
        "failed_urls": result.failed_urls,
        "container_timeline": result.container_timeline,
        "per_worker_stats": {
            str(k): v for k, v in result.per_worker_stats.items()
        },
    }
    meta_path = output_dir / "scaling_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, default=str))
    console.print(f"  Saved {meta_path}")
