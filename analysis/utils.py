"""Shared utility functions for the analysis package.

Provides common helpers used across scaling analysis, quality comparison,
statistics generation, and orchestration scripts.  Functions were extracted
from analyze_scaling.py, generate_scaling_stats.py, compare_scaling_quality.py,
and run.py to eliminate duplication.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import subprocess
from pathlib import Path


# ── Statistics helpers ────────────────────────────────────────────────────


def percentile(data: list[float], p: float) -> float:
    """Compute percentile (0-100) with linear interpolation.

    Parameters
    ----------
    data:
        Non-empty sequence of numeric values.
    p:
        Desired percentile in the range [0, 100].

    Returns
    -------
    float
        The interpolated percentile value.
    """
    s = sorted(data)
    n = len(s)
    k = (p / 100) * (n - 1)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def compute_stats(values: list[float]) -> dict | None:
    """Compute descriptive statistics for a list of values.

    Returns a dict with keys ``avg``, ``std``, ``min``, ``p25``, ``median``,
    ``p75``, ``max``.  Returns ``None`` when *values* is empty.
    """
    if not values:
        return None
    return {
        "avg": statistics.mean(values),
        "std": statistics.pstdev(values),
        "min": min(values),
        "p25": percentile(values, 25),
        "median": statistics.median(values),
        "p75": percentile(values, 75),
        "max": max(values),
    }


# ── Formatting helpers ───────────────────────────────────────────────────


def normalize_host(host: str) -> str:
    """Strip ``www.`` prefix so hosts match regardless of subdomain."""
    return host.removeprefix("www.")


def fmt(v, decimals: int = 0) -> str:
    """Format a value for display in Markdown tables.

    * ``None`` or empty string becomes an em-dash (``—``).
    * ``-1`` (used as a sentinel for "never completed") becomes ``"NEVER"``.
    * Floats are formatted with *decimals* decimal places and thousands separators.
    * Integers are formatted with thousands separators.
    * Everything else is passed through ``str()``.
    """
    if v is None or v == "":
        return "—"
    if isinstance(v, float):
        if v == -1:
            return "NEVER"
        return f"{v:,.{decimals}f}"
    if isinstance(v, int):
        if v == -1:
            return "NEVER"
        return f"{v:,}"
    return str(v)


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a Markdown table with column-width alignment.

    The first column is left-aligned; remaining columns are right-aligned.

    Parameters
    ----------
    headers:
        Column header strings.
    rows:
        List of rows, each row a list of cell strings.

    Returns
    -------
    str
        A complete Markdown table as a single string (no trailing newline).
    """
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(cell))

    def _pad(cells):
        return "| " + " | ".join(
            c.ljust(col_widths[i]) if i == 0 else c.rjust(col_widths[i])
            for i, c in enumerate(cells)
        ) + " |"

    sep = "|" + "|".join(
        "-" * (col_widths[i] + 2) for i in range(len(headers))
    ) + "|"

    lines = [_pad(headers), sep]
    for row in rows:
        lines.append(_pad(row))
    return "\n".join(lines)


def pct_change(baseline: float, value: float) -> str:
    """Return a percentage-change string relative to *baseline*.

    Special cases:

    * Both zero -> ``"="``
    * Baseline zero, value non-zero -> ``"+inf"``
    * Change smaller than 0.5% -> ``"="``
    """
    if baseline == 0:
        return "—" if value == 0 else "+inf"
    delta = (value - baseline) / abs(baseline) * 100
    if abs(delta) < 0.5:
        return "="
    return f"{delta:+.0f}%"


def severity_marker(pct_str: str) -> str:
    """Append ``!`` markers to a percentage-change string for large deviations.

    * ``>50%`` gets ``!!!``
    * ``>20%`` gets ``!!``
    * ``>10%`` gets ``!``
    """
    if pct_str in ("=", "—", "+inf"):
        return pct_str
    try:
        val = float(pct_str.rstrip("%").replace("+", ""))
    except ValueError:
        return pct_str
    if abs(val) > 50:
        return pct_str + " !!!"
    if abs(val) > 20:
        return pct_str + " !!"
    if abs(val) > 10:
        return pct_str + " !"
    return pct_str


# ── Data loading ─────────────────────────────────────────────────────────


def load_scaling_job(job_dir: Path) -> dict:
    """Load all scaling configurations grouped by mode from *job_dir*.

    Each sub-directory is expected to contain a ``scaling_meta.json`` and a
    ``raw_metrics_{mode}.json``.  When ``scaling_meta.json`` is missing the
    function falls back to inferring mode and worker count from the directory
    name (pattern: ``{mode}_{N}w``).

    Returns
    -------
    dict
        ``{mode: [(num_workers, meta_dict, {norm_host: metrics_dict}), ...]}``
        sorted by worker count within each mode.
    """
    by_mode: dict[str, list] = {}

    for sub in sorted(job_dir.iterdir()):
        if not sub.is_dir():
            continue

        meta_path = sub / "scaling_meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            mode = meta["mode"]
            nw = meta["num_workers"]
        else:
            # Infer mode and workers from directory name: {mode}_{N}w
            m = re.match(r"^(.+)_(\d+)w$", sub.name)
            if not m:
                continue
            mode = m.group(1)
            nw = int(m.group(2))
            meta = {
                "wall_time_s": 0,
                "urls_ok": 0,
                "urls_failed": 0,
                "urls_total": 0,
                "container_timeline": [],
                "per_worker_stats": {},
            }

        raw_path = sub / f"raw_metrics_{mode}.json"
        if not raw_path.exists():
            continue
        raw = json.loads(raw_path.read_text())

        # Backfill urls_ok/urls_total from raw data when meta is synthetic
        if meta["urls_total"] == 0 and raw:
            ok = sum(1 for e in raw if mode in e and not e[mode].get("error"))
            meta["urls_total"] = len(raw)
            meta["urls_ok"] = ok
            meta["urls_failed"] = len(raw) - ok

        by_host: dict[str, dict] = {}
        for entry in raw:
            host = normalize_host(entry.get("host", ""))
            if mode in entry:
                by_host[host] = entry[mode]

        by_mode.setdefault(mode, []).append((nw, meta, by_host))

    for cfgs in by_mode.values():
        cfgs.sort(key=lambda x: x[0])

    return by_mode


def load_baseline_from_job(job_dir: Path, mode: str) -> dict[str, dict]:
    """Load 1-worker baseline metrics from a regular (non-scaling) job.

    Reads ``raw_metrics.json`` (merged format) or ``raw_metrics_{mode}.json``
    and extracts per-host metrics for the given *mode*, skipping entries that
    contain an ``error`` key.
    """
    raw_path = job_dir / "raw_metrics.json"
    if not raw_path.exists():
        raw_path = job_dir / f"raw_metrics_{mode}.json"
    if not raw_path.exists():
        return {}

    raw = json.loads(raw_path.read_text())
    by_host: dict[str, dict] = {}
    for entry in raw:
        host = normalize_host(entry.get("host", ""))
        if mode in entry and not entry[mode].get("error"):
            by_host[host] = entry[mode]
    return by_host


# ── URL / process helpers ────────────────────────────────────────────────


def load_urls(path: Path, limit: int = 0) -> list[str]:
    """Load URLs from a text file, one per line.

    Blank lines and lines starting with ``#`` are skipped.  Duplicate URLs
    are removed (first occurrence wins).  When *limit* is greater than zero
    only the first *limit* URLs are returned.
    """
    seen: set[str] = set()
    urls: list[str] = []
    for line in path.read_text().splitlines():
        url = line.strip()
        if not url or url.startswith("#") or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    if limit > 0:
        urls = urls[:limit]
    return urls


def run_cmd(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    """Run *cmd* as a subprocess, printing the command line first.

    Parameters
    ----------
    cmd:
        Command and arguments (passed to :func:`subprocess.run`).
    check:
        If ``True`` (default), raise :class:`subprocess.CalledProcessError`
        on non-zero exit.
    """
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)
