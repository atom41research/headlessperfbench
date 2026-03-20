#!/usr/bin/env python3
"""Generate scaling_report.md comparing performance across worker counts.

Moved from generate_scaling_stats.py at project root into the analysis package.
Uses shared percentile() from analysis.utils; keeps its own compute_stats()
and timeline_stats() (different return shape from the shared version).

Usage:
    uv run python -m analysis.scaling_stats output/jobs/scaling_YYYYMMDD_HHMMSS
"""

import csv
import json
import math
import re
import statistics
import sys
from pathlib import Path

from .utils import percentile


def compute_stats(values: list[float]) -> dict | None:
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


def load_configs(job_dir: Path) -> list[dict]:
    """Load all scaling_meta.json files under *job_dir*.

    Falls back to inferring mode/workers from directory name when
    scaling_meta.json is missing (e.g. 1-worker sequential runs).
    """
    configs = []
    for sub in sorted(job_dir.iterdir()):
        if not sub.is_dir():
            continue
        meta_path = sub / "scaling_meta.json"
        if meta_path.exists():
            data = json.loads(meta_path.read_text())
        else:
            # Infer from directory name: {mode}_{N}w
            m = re.match(r"^(.+)_(\d+)w$", sub.name)
            if not m:
                continue
            mode = m.group(1)
            nw = int(m.group(2))
            raw_path = sub / f"raw_metrics_{mode}.json"
            if not raw_path.exists():
                continue
            raw = json.loads(raw_path.read_text())
            ok = sum(1 for e in raw if mode in e and not e[mode].get("error"))
            data = {
                "mode": mode,
                "num_workers": nw,
                "wall_time_s": 0,
                "urls_total": len(raw),
                "urls_ok": ok,
                "urls_failed": len(raw) - ok,
                "container_timeline": [],
                "per_worker_stats": {},
            }
        data["_dir"] = sub
        data["_dir_name"] = sub.name
        configs.append(data)
    return configs


def timeline_stats(timeline: list[dict], key: str) -> dict | None:
    """Compute stats over a timeline's field."""
    values = [s[key] for s in timeline if key in s]
    if not values:
        return None
    return {
        "avg": statistics.mean(values),
        "peak": max(values),
        "p95": percentile(values, 95) if len(values) >= 2 else max(values),
        "min": min(values),
    }


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m analysis.scaling_stats <job_dir>")
        sys.exit(1)

    job_dir = Path(sys.argv[1])
    configs = load_configs(job_dir)
    if not configs:
        print(f"No scaling_meta.json files found in {job_dir}")
        sys.exit(1)

    # Group by mode
    by_mode: dict[str, list[dict]] = {}
    for cfg in configs:
        by_mode.setdefault(cfg["mode"], []).append(cfg)

    # Sort each mode's configs by worker count
    for cfgs in by_mode.values():
        cfgs.sort(key=lambda c: c["num_workers"])

    lines: list[str] = []
    lines.append(f"# Scaling Report — {len(configs)} Configurations\n")
    lines.append(f"Job: `{job_dir.name}`\n")
    lines.append("---\n")

    # ── Throughput ────────────────────────────────────────────────────
    for mode, cfgs in by_mode.items():
        lines.append(f"## {mode}\n")

        # Find baseline (1 worker) wall time for speedup calculation
        baseline_time = None
        for c in cfgs:
            if c["num_workers"] == 1 and c["wall_time_s"] > 0:
                baseline_time = c["wall_time_s"]
                break

        # Throughput table
        lines.append("### Throughput\n")
        lines.append("| Workers | Wall Time (s) | URLs OK | URLs Failed | URLs/sec | Speedup | Efficiency |")
        lines.append("|--------:|--------------:|--------:|------------:|---------:|--------:|-----------:|")

        for c in cfgs:
            w = c["num_workers"]
            wt = c["wall_time_s"]
            ok = c["urls_ok"]
            fail = c["urls_failed"]
            rate = ok / wt if wt > 0 else 0
            if baseline_time and baseline_time > 0:
                speedup = baseline_time / wt
                efficiency = speedup / w * 100
            else:
                speedup = 1.0 if w == 1 else float("nan")
                efficiency = 100.0 if w == 1 else float("nan")

            speedup_str = f"{speedup:.2f}x" if not math.isnan(speedup) else "—"
            eff_str = f"{efficiency:.0f}%" if not math.isnan(efficiency) else "—"
            lines.append(
                f"| {w:>7} | {wt:>13.1f} | {ok:>7} | {fail:>11} | "
                f"{rate:>8.2f} | {speedup_str:>7} | {eff_str:>10} |"
            )

        # Container memory table
        lines.append("\n### Container Memory\n")
        lines.append("| Workers | Avg Mem (MB) | Peak Mem (MB) | P95 Mem (MB) | Avg Active (MB) | Peak Active (MB) |")
        lines.append("|--------:|-------------:|--------------:|-------------:|----------------:|-----------------:|")

        for c in cfgs:
            tl = c.get("container_timeline", [])
            if not tl:
                lines.append(f"| {c['num_workers']:>7} | — | — | — | — | — |")
                continue
            mem = timeline_stats(tl, "memory_current_mb")
            act = timeline_stats(tl, "active_memory_mb")
            if mem and act:
                lines.append(
                    f"| {c['num_workers']:>7} | {mem['avg']:>12.0f} | {mem['peak']:>13.0f} | "
                    f"{mem['p95']:>12.0f} | {act['avg']:>15.0f} | {act['peak']:>16.0f} |"
                )
            else:
                lines.append(f"| {c['num_workers']:>7} | — | — | — | — | — |")

        # Container CPU table
        lines.append("\n### Container CPU\n")
        lines.append("| Workers | Avg CPU% | Peak CPU% | P95 CPU% |")
        lines.append("|--------:|---------:|----------:|---------:|")

        for c in cfgs:
            tl = c.get("container_timeline", [])
            if not tl:
                lines.append(f"| {c['num_workers']:>7} | — | — | — |")
                continue
            cpu = timeline_stats(tl, "cpu_pct")
            if cpu:
                lines.append(
                    f"| {c['num_workers']:>7} | {cpu['avg']:>8.0f} | "
                    f"{cpu['peak']:>9.0f} | {cpu['p95']:>8.0f} |"
                )
            else:
                lines.append(f"| {c['num_workers']:>7} | — | — | — |")

        # Worker utilization
        lines.append("\n### Worker Utilization\n")
        lines.append("| Workers | Worker ID | URLs | Failed | Wall Time (s) |")
        lines.append("|--------:|----------:|-----:|-------:|--------------:|")

        for c in cfgs:
            ws = c.get("per_worker_stats", {})
            for wid in sorted(ws, key=int):
                s = ws[wid]
                lines.append(
                    f"| {c['num_workers']:>7} | {wid:>9} | "
                    f"{s['urls_processed']:>4} | {s['urls_failed']:>6} | "
                    f"{s.get('total_wall_time_s', 0):>13.1f} |"
                )

        lines.append("")

    # ── Result consistency ────────────────────────────────────────────
    lines.append("## Result Consistency\n")
    lines.append("Comparing per-URL metrics across worker counts to check for "
                 "concurrency effects.\n")

    for mode, cfgs in by_mode.items():
        if len(cfgs) < 2:
            continue

        lines.append(f"### {mode}\n")

        # Load raw metrics for each config
        config_metrics: dict[int, dict[str, dict]] = {}  # workers -> {host: metrics}
        for c in cfgs:
            raw_path = c["_dir"] / f"raw_metrics_{mode}.json"
            if not raw_path.exists():
                continue
            data = json.loads(raw_path.read_text())
            by_host: dict[str, dict] = {}
            for entry in data:
                host = entry.get("host", "")
                if mode in entry:
                    by_host[host] = entry[mode]
            config_metrics[c["num_workers"]] = by_host

        if len(config_metrics) < 2:
            lines.append("Insufficient data for comparison.\n")
            continue

        # Find hosts present in all configs
        all_hosts = None
        for hosts in config_metrics.values():
            if all_hosts is None:
                all_hosts = set(hosts.keys())
            else:
                all_hosts &= set(hosts.keys())

        if not all_hosts:
            lines.append("No common URLs across all configurations.\n")
            continue

        # For each host, compute coefficient of variation for key metrics
        metrics_to_check = [
            "dom_element_count", "dom_size_bytes", "network_request_count",
            "visible_text_length",
        ]

        lines.append(f"Common URLs: {len(all_hosts)}\n")
        lines.append("| Metric | Avg CV% | Max CV% | Hosts with CV>20% |")
        lines.append("|--------|--------:|--------:|------------------:|")

        for metric in metrics_to_check:
            cvs: list[float] = []
            high_cv = 0
            for host in sorted(all_hosts):
                values = []
                for w, hosts_data in config_metrics.items():
                    v = hosts_data.get(host, {}).get(metric)
                    if v is not None and v != 0:
                        values.append(float(v))
                if len(values) >= 2:
                    mean = statistics.mean(values)
                    if mean > 0:
                        cv = statistics.pstdev(values) / mean * 100
                        cvs.append(cv)
                        if cv > 20:
                            high_cv += 1

            if cvs:
                lines.append(
                    f"| {metric:<30} | {statistics.mean(cvs):>7.1f} | "
                    f"{max(cvs):>7.1f} | {high_cv:>17} |"
                )
            else:
                lines.append(f"| {metric:<30} | — | — | — |")

        lines.append("")

    # ── Timeline CSV export ───────────────────────────────────────────
    lines.append("## Timeline Data\n")
    lines.append("Exported per-configuration timeline CSVs for plotting:\n")

    for cfg in configs:
        tl = cfg.get("container_timeline", [])
        if not tl:
            continue
        csv_name = f"timeline_{cfg['_dir_name']}.csv"
        csv_path = job_dir / csv_name
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["t", "memory_current_mb", "active_memory_mb", "cpu_pct"],
            )
            writer.writeheader()
            for sample in tl:
                writer.writerow({
                    "t": sample["t"],
                    "memory_current_mb": sample["memory_current_mb"],
                    "active_memory_mb": sample["active_memory_mb"],
                    "cpu_pct": sample["cpu_pct"],
                })
        lines.append(f"- `{csv_name}`")

    lines.append("")

    # ── Write report ──────────────────────────────────────────────────
    report_path = job_dir / "scaling_report.md"
    report_path.write_text("\n".join(lines))
    print(f"Written to {report_path}")


if __name__ == "__main__":
    main()
