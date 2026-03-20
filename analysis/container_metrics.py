#!/usr/bin/env python3
"""Analyze container cgroup memory metrics to identify page cache vs process memory.

Moved from analyze_container_metrics.py at project root into the analysis package.
Uses shared percentile() from analysis.utils.

Reads raw_metrics.json and shows how container_total_memory (memory.current)
includes page cache that accumulates over time, vs container_active_memory
(anon + kernel) which reflects actual process memory.
"""

import json
import statistics
import sys
from pathlib import Path

from .utils import percentile

MODES = ["headful", "headless", "headless-shell"]
MODE_SHORT = {"headful": "HF", "headless": "HL", "headless-shell": "Shell"}
BUCKET_SIZE = 100


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python -m analysis container-metrics <job_dir>")
        print("\nContainer cgroup memory analysis.")
        print("Reads raw_metrics.json from <job_dir>.")
        print("Prints bucketed memory progression and cross-validation tables.")
        sys.exit(0 if len(sys.argv) >= 2 else 1)

    job_dir = Path(sys.argv[1])
    raw_path = job_dir / "raw_metrics.json"
    data = json.loads(raw_path.read_text())

    # Filter to entries where all modes succeeded and have container metrics
    valid = []
    for entry in data:
        ok = True
        for m in MODES:
            md = entry.get(m, {})
            if not md or md.get("error"):
                ok = False
                break
            if md.get("container_total_memory_mb", 0) == 0:
                ok = False
                break
        if ok:
            valid.append(entry)

    if not valid:
        print("No entries with container metrics found.")
        sys.exit(1)

    n = len(valid)
    print(f"# Container Memory Analysis — {n} URLs with container metrics\n")

    # ── Bucketed progression ──────────────────────────────────────────────
    buckets = []
    for start in range(0, n, BUCKET_SIZE):
        end = min(start + BUCKET_SIZE, n)
        bucket_entries = valid[start:end]
        label = f"{start+1}-{end}"
        bucket = {"label": label, "n": len(bucket_entries)}
        for m in MODES:
            total = [e[m]["container_total_memory_mb"] for e in bucket_entries]
            active = [e[m]["container_active_memory_mb"] for e in bucket_entries]
            cache = [t - a for t, a in zip(total, active)]
            bucket[m] = {
                "total_avg": statistics.mean(total),
                "active_avg": statistics.mean(active),
                "cache_avg": statistics.mean(cache),
            }
        buckets.append(bucket)

    # Table 1: Container Total Memory (memory.current) progression
    print("## Container Total Memory (memory.current) — includes page cache\n")
    print(f"{'Bucket':<12} {'n':>4}  {'HF':>10}  {'HL':>10}  {'Shell':>10}")
    print(f"{'-'*12} {'---':>4}  {'---':>10}  {'---':>10}  {'---':>10}")
    for b in buckets:
        print(
            f"{b['label']:<12} {b['n']:>4}  "
            f"{b['headful']['total_avg']:>10.0f}  "
            f"{b['headless']['total_avg']:>10.0f}  "
            f"{b['headless-shell']['total_avg']:>10.0f}"
        )

    # Table 2: Container Active Memory (anon + kernel) progression
    print(f"\n## Container Active Memory (anon + kernel) — process memory only\n")
    print(f"{'Bucket':<12} {'n':>4}  {'HF':>10}  {'HL':>10}  {'Shell':>10}")
    print(f"{'-'*12} {'---':>4}  {'---':>10}  {'---':>10}  {'---':>10}")
    for b in buckets:
        print(
            f"{b['label']:<12} {b['n']:>4}  "
            f"{b['headful']['active_avg']:>10.0f}  "
            f"{b['headless']['active_avg']:>10.0f}  "
            f"{b['headless-shell']['active_avg']:>10.0f}"
        )

    # Table 3: Page cache component (total - active)
    print(f"\n## Page Cache Component (total - active)\n")
    print(f"{'Bucket':<12} {'n':>4}  {'HF':>10}  {'HL':>10}  {'Shell':>10}")
    print(f"{'-'*12} {'---':>4}  {'---':>10}  {'---':>10}  {'---':>10}")
    for b in buckets:
        print(
            f"{b['label']:<12} {b['n']:>4}  "
            f"{b['headful']['cache_avg']:>10.0f}  "
            f"{b['headless']['cache_avg']:>10.0f}  "
            f"{b['headless-shell']['cache_avg']:>10.0f}"
        )

    # ── Overall vs last-bucket comparison ─────────────────────────────────
    print(f"\n## Overall Averages vs Last {BUCKET_SIZE} URLs\n")

    for m in MODES:
        all_total = [e[m]["container_total_memory_mb"] for e in valid]
        all_active = [e[m]["container_active_memory_mb"] for e in valid]
        last_total = [e[m]["container_total_memory_mb"] for e in valid[-BUCKET_SIZE:]]
        last_active = [e[m]["container_active_memory_mb"] for e in valid[-BUCKET_SIZE:]]

        print(f"### {m}")
        print(f"  Total memory:  overall avg = {statistics.mean(all_total):>8.0f} MB,  last-{BUCKET_SIZE} avg = {statistics.mean(last_total):>8.0f} MB  (delta: +{statistics.mean(last_total) - statistics.mean(all_total):>.0f} MB)")
        print(f"  Active memory: overall avg = {statistics.mean(all_active):>8.0f} MB,  last-{BUCKET_SIZE} avg = {statistics.mean(last_active):>8.0f} MB  (delta: +{statistics.mean(last_active) - statistics.mean(all_active):>.0f} MB)")
        print(f"  Page cache:    overall avg = {statistics.mean(all_total) - statistics.mean(all_active):>8.0f} MB,  last-{BUCKET_SIZE} avg = {statistics.mean(last_total) - statistics.mean(last_active):>8.0f} MB")
        print()

    # ── Conclusion ────────────────────────────────────────────────────────
    print("## Conclusion\n")
    print("container_total_memory_mb (memory.current) includes Linux page cache,")
    print("which accumulates monotonically as URLs are processed. All modes converge")
    print("to similar totals by the end of the run — the metric reflects OS disk cache,")
    print("not browser overhead.\n")
    print("container_active_memory_mb (anon + kernel) excludes page cache and reflects")
    print("actual process memory. This is the meaningful metric for mode comparison.\n")

    # ── Chrome RSS vs Container Active for cross-validation ───────────────
    print("## Cross-Validation: Chrome RSS vs Container Active Memory\n")
    print(f"{'Metric':<30} {'HF':>10}  {'HL':>10}  {'Shell':>10}")
    print(f"{'-'*30} {'---':>10}  {'---':>10}  {'---':>10}")

    for key, label in [
        ("chrome_avg_rss_mb", "Chrome avg RSS (MB)"),
        ("chrome_avg_uss_mb", "Chrome avg USS (MB)"),
        ("container_active_memory_mb", "Container Active Mem (MB)"),
        ("container_total_memory_mb", "Container Total Mem (MB)"),
    ]:
        vals = {}
        for m in MODES:
            v = [e[m].get(key, 0) for e in valid if e[m].get(key, 0) > 0]
            vals[m] = statistics.mean(v) if v else 0
        print(f"{label:<30} {vals['headful']:>10.0f}  {vals['headless']:>10.0f}  {vals['headless-shell']:>10.0f}")

    print()
    print("Container Active Memory > Chrome USS because it includes Python/Playwright")
    print("processes and kernel allocations beyond Chrome's own heap.")


if __name__ == "__main__":
    main()
