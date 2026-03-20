#!/usr/bin/env python3
"""Compare result quality and performance across scaling configurations.

Moved from compare_scaling_quality.py at project root into the analysis package.
Uses shared helpers from analysis.utils instead of local definitions.

Loads all configs from a scaling job directory and produces a side-by-side
comparison of quality metrics, navigation timing, resource usage, and
flags degradation at higher concurrency levels.

Usage:
    uv run python -m analysis.scaling_comparison output/jobs/scaling_YYYYMMDD_HHMMSS
    uv run python -m analysis.scaling_comparison output/jobs/scaling_XXX \
        --baseline-job output/jobs/job_YYY
"""

import argparse
import statistics
import sys
from pathlib import Path

from .utils import (
    fmt,
    load_baseline_from_job,
    load_scaling_job,
    normalize_host,
    pct_change,
    severity_marker,
)


# ── Report generation ────────────────────────────────────────────────────


def generate_comparison(job_dir: Path, baseline_job: Path | None = None) -> str:
    by_mode = load_scaling_job(job_dir)
    if not by_mode:
        return "No scaling data found."

    lines: list[str] = []
    lines.append(f"# Scaling Quality Comparison — `{job_dir.name}`\n")
    if baseline_job:
        lines.append(f"Baseline (1w): `{baseline_job.name}`\n")

    for mode, cfgs in by_mode.items():
        # Inject 1-worker baseline from external job if provided
        if baseline_job:
            baseline_hosts = load_baseline_from_job(baseline_job, mode)
            if baseline_hosts:
                synthetic_meta = {
                    "wall_time_s": 0,
                    "urls_ok": len(baseline_hosts),
                    "urls_failed": 0,
                    "container_timeline": [],
                }
                cfgs.insert(0, (1, synthetic_meta, baseline_hosts))

        worker_counts = [nw for nw, _, _ in cfgs]
        col_labels = [f"{nw}w" for nw in worker_counts]
        baseline_idx = 0  # lowest worker count is baseline

        lines.append(f"## Mode: {mode}\n")
        lines.append(f"Configurations: {', '.join(col_labels)}  |  "
                      f"Baseline: {col_labels[baseline_idx]}\n")

        # Find common hosts across all configs
        all_hosts = None
        for _, _, by_host in cfgs:
            hosts = set(by_host.keys())
            all_hosts = hosts if all_hosts is None else all_hosts & hosts
        if not all_hosts:
            lines.append("No common URLs.\n")
            continue
        hosts_sorted = sorted(all_hosts)

        # ── Overview table ───────────────────────────────────────────
        lines.append("### Overview\n")
        header = "| Metric |" + "|".join(f" {c:>8} " for c in col_labels) + "|"
        sep = "|--------|" + "|".join("-" * 10 for _ in col_labels) + "|"
        lines.append(header)
        lines.append(sep)

        # Wall time
        cells = []
        for _, meta, _ in cfgs:
            wt = meta["wall_time_s"]
            cells.append(f" {wt:>8.1f} " if wt > 0 else "        — ")
        lines.append("| Wall time (s) |" + "|".join(cells) + "|")

        # URLs compared
        lines.append(f"| URLs compared |" + "|".join(
            f" {len(all_hosts):>8} " for _ in cfgs) + "|")

        # Container metrics
        for label, key in [
            ("Peak mem (MB)", "memory_current_mb"),
            ("Peak active (MB)", "active_memory_mb"),
            ("Avg CPU%", "cpu_pct"),
        ]:
            cells = []
            for _, meta, _ in cfgs:
                tl = meta.get("container_timeline", [])
                if not tl:
                    cells.append("       —")
                    continue
                vals = [s[key] for s in tl if key in s]
                if key == "cpu_pct":
                    cells.append(f"{statistics.mean(vals):>8.0f}" if vals else "       —")
                else:
                    cells.append(f"{max(vals):>8.0f}" if vals else "       —")
            row = f"| {label} |" + "|".join(f" {c} " for c in cells) + "|"
            lines.append(row)
        lines.append("")

        # ── Quality: per-URL side-by-side ────────────────────────────
        quality_metrics = [
            ("DOM elements", "dom_element_count", 0),
            ("DOM size (KB)", "dom_size_bytes", 0),
            ("Visible text", "visible_text_length", 0),
            ("Net requests", "network_request_count", 0),
            ("HTTP status", "http_status", 0),
        ]

        timing_metrics = [
            ("TTFB", "ttfb_ms", 0),
            ("DOM interactive", "dom_interactive_ms", 0),
            ("DOM complete", "dom_complete_ms", 0),
            ("Load event", "load_event_ms", 0),
        ]

        resource_metrics = [
            ("CPU time (s)", "cpu_time_s", 2),
            ("Chrome RSS (MB)", "chrome_avg_rss_mb", 0),
            ("Chrome USS (MB)", "chrome_avg_uss_mb", 0),
        ]

        for section_name, metrics_list in [
            ("Quality Metrics", quality_metrics),
            ("Navigation Timing (ms)", timing_metrics),
            ("Per-Instance Resources", resource_metrics),
        ]:
            lines.append(f"### {section_name}\n")

            for host in hosts_sorted:
                lines.append(f"#### {host}\n")

                hdr_parts = ["| Metric"]
                sep_parts = ["|--------"]
                for i, label in enumerate(col_labels):
                    hdr_parts.append(f" {label:>10}")
                    sep_parts.append("-" * 11)
                    if i > 0:
                        hdr_parts.append(f" {'Δ':>7}")
                        sep_parts.append("-" * 8)
                hdr_parts.append("|")
                sep_parts.append("|")
                lines.append("|".join(hdr_parts))
                lines.append("|".join(sep_parts))

                for label, key, dec in metrics_list:
                    row_parts = [f"| {label:<20}"]

                    baseline_val = None
                    for i, (nw, meta, by_host) in enumerate(cfgs):
                        m = by_host.get(host, {})
                        v = m.get(key)

                        if key == "dom_size_bytes" and v is not None:
                            v = v / 1024

                        if i == 0:
                            baseline_val = v

                        row_parts.append(f" {fmt(v, dec):>10}")
                        if i > 0:
                            if baseline_val is not None and v is not None and baseline_val != -1 and v != -1:
                                delta = severity_marker(pct_change(baseline_val, v))
                            elif v == -1 and baseline_val != -1:
                                delta = "NEVER !!"
                            else:
                                delta = "—"
                            row_parts.append(f" {delta:>7}")

                    row_parts.append("|")
                    lines.append("|".join(row_parts))

                lines.append("")

        # ── Degradation summary ──────────────────────────────────────
        lines.append("### Degradation Summary\n")
        lines.append("URLs with significant quality loss vs baseline "
                      f"({col_labels[baseline_idx]}):\n")

        degradation_keys = [
            ("dom_element_count", "DOM elements", 10),
            ("dom_size_bytes", "DOM size", 10),
            ("visible_text_length", "Visible text", 10),
            ("network_request_count", "Net requests", 15),
        ]

        lines.append("| URL | Workers | Metric | Baseline | Value | Change |")
        lines.append("|-----|---------|--------|----------|-------|--------|")

        any_degradation = False
        for host in hosts_sorted:
            baseline_metrics = cfgs[baseline_idx][2].get(host, {})
            for i, (nw, meta, by_host) in enumerate(cfgs):
                if i == baseline_idx:
                    continue
                m = by_host.get(host, {})
                for key, label, threshold in degradation_keys:
                    bv = baseline_metrics.get(key, 0)
                    cv = m.get(key, 0)
                    if bv and cv and bv > 0:
                        change = (cv - bv) / bv * 100
                        if abs(change) > threshold:
                            lines.append(
                                f"| {host} | {nw}w | {label} | "
                                f"{fmt(bv)} | {fmt(cv)} | {change:+.0f}% |"
                            )
                            any_degradation = True

                # Check dom_complete going to -1
                bv = baseline_metrics.get("dom_complete_ms", -1)
                cv = m.get("dom_complete_ms", -1)
                if bv > 0 and cv == -1:
                    lines.append(
                        f"| {host} | {nw}w | DOM complete | "
                        f"{fmt(bv, 0)}ms | NEVER | page incomplete |"
                    )
                    any_degradation = True

                # Check HTTP status changes
                bv = baseline_metrics.get("http_status", 0)
                cv = m.get("http_status", 0)
                if bv != cv and bv > 0:
                    lines.append(
                        f"| {host} | {nw}w | HTTP status | "
                        f"{bv} | {cv} | status change |"
                    )
                    any_degradation = True

        if not any_degradation:
            lines.append("| — | — | — | — | — | No degradation detected |")
        lines.append("")

        # ── Quality score per config ─────────────────────────────────
        lines.append("### Quality Score\n")
        lines.append("Composite score: 100 = identical to baseline, lower = worse.\n")
        lines.append("| Workers | DOM Score | Content Score | Network Score | "
                      "Timing Score | Overall |")
        lines.append("|---------|----------|---------------|---------------|"
                      "-------------|---------|")

        for i, (nw, meta, by_host) in enumerate(cfgs):
            dom_scores, content_scores, net_scores, timing_scores = [], [], [], []

            baseline_hosts_data = cfgs[baseline_idx][2]
            for host in hosts_sorted:
                bm = baseline_hosts_data.get(host, {})
                cm = by_host.get(host, {})
                if not bm or not cm:
                    continue

                b, c = bm.get("dom_element_count", 0), cm.get("dom_element_count", 0)
                if b > 0:
                    dom_scores.append(min(c / b, b / c) * 100 if c > 0 else 0)

                b, c = bm.get("visible_text_length", 0), cm.get("visible_text_length", 0)
                if b > 0:
                    content_scores.append(min(c / b, b / c) * 100 if c > 0 else 0)

                b, c = bm.get("network_request_count", 0), cm.get("network_request_count", 0)
                if b > 0:
                    net_scores.append(min(c / b, 1.0) * 100)

                b_dc = bm.get("dom_complete_ms", -1)
                c_dc = cm.get("dom_complete_ms", -1)
                if b_dc > 0:
                    if c_dc == -1:
                        timing_scores.append(0)
                    else:
                        ratio = b_dc / c_dc if c_dc > 0 else 0
                        timing_scores.append(min(ratio, 1.0) * 100)

            dom = statistics.mean(dom_scores) if dom_scores else 0
            content = statistics.mean(content_scores) if content_scores else 0
            net = statistics.mean(net_scores) if net_scores else 0
            timing = statistics.mean(timing_scores) if timing_scores else 0
            overall = (dom * 0.3 + content * 0.3 + net * 0.2 + timing * 0.2)

            lines.append(
                f"| {nw}w | {dom:>8.1f} | {content:>13.1f} | {net:>13.1f} | "
                f"{timing:>11.1f} | **{overall:>5.1f}** |"
            )

        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Compare scaling quality across worker counts.",
    )
    parser.add_argument("job_dir", type=Path,
                        help="Scaling job directory")
    parser.add_argument("--baseline-job", type=Path, default=None,
                        help="Regular job directory to use as 1-worker baseline")
    args = parser.parse_args()

    if not args.job_dir.exists():
        print(f"Error: {args.job_dir} not found")
        sys.exit(1)
    if args.baseline_job and not args.baseline_job.exists():
        print(f"Error: {args.baseline_job} not found")
        sys.exit(1)

    report = generate_comparison(args.job_dir, baseline_job=args.baseline_job)

    out_path = args.job_dir / "quality_comparison.md"
    out_path.write_text(report)
    print(report)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
