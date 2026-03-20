#!/usr/bin/env python3
"""Summary analysis of scaling quality: does adding more workers hurt quality?

Moved from analyze_scaling.py at project root into the analysis package.
Uses shared helpers from analysis.utils instead of local definitions.

Produces compact summary tables focused on quality degradation patterns,
complementing the per-URL deep dive in scaling_comparison.py.

Usage:
    uv run python -m analysis.scaling_quality output/jobs/scaling_YYYYMMDD_HHMMSS
    uv run python -m analysis.scaling_quality output/jobs/scaling_XXX \
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
    md_table,
    normalize_host,
)


# ── Report generation ────────────────────────────────────────────────────


def generate_analysis(job_dir: Path, baseline_job: Path | None = None) -> str:
    by_mode = load_scaling_job(job_dir)
    if not by_mode:
        return "No scaling data found."

    lines: list[str] = []
    lines.append(f"# Scaling Analysis — `{job_dir.name}`\n")
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
                    "urls_total": len(baseline_hosts),
                    "container_timeline": [],
                }
                cfgs.insert(0, (1, synthetic_meta, baseline_hosts))

        worker_counts = [nw for nw, _, _ in cfgs]

        lines.append(f"## Mode: {mode}\n")

        # Find common hosts across all configs
        all_hosts = None
        for _, _, by_host in cfgs:
            hosts = set(by_host.keys())
            all_hosts = hosts if all_hosts is None else all_hosts & hosts
        if not all_hosts:
            lines.append("No common URLs across configurations.\n")
            continue
        hosts_sorted = sorted(all_hosts)

        # ── Table 1: Throughput & Resources Overview ──────────────────
        lines.append("### Table 1: Throughput & Resources Overview\n")
        t1_headers = ["Workers", "Wall Time", "URLs/sec", "Speedup",
                       "Peak Mem MB", "Peak Active MB", "Avg CPU%"]
        t1_rows = []
        baseline_wall = None
        for nw, meta, _ in cfgs:
            wt = meta["wall_time_s"]
            urls_total = meta.get("urls_total", meta.get("urls_ok", 0))

            if baseline_wall is None and wt > 0:
                baseline_wall = wt

            wall_str = f"{wt:.1f}s" if wt > 0 else "—"
            urls_sec = f"{urls_total / wt:.2f}" if wt > 0 else "—"
            speedup = f"{baseline_wall / wt:.2f}x" if wt > 0 and baseline_wall else "—"

            tl = meta.get("container_timeline", [])
            if tl:
                mem_vals = [s.get("memory_current_mb", 0) for s in tl]
                active_vals = [s.get("active_memory_mb", 0) for s in tl]
                cpu_vals = [s.get("cpu_pct", 0) for s in tl]
                peak_mem = f"{max(mem_vals):.0f}"
                peak_active = f"{max(active_vals):.0f}"
                avg_cpu = f"{statistics.mean(cpu_vals):.0f}"
            else:
                peak_mem = peak_active = avg_cpu = "—"

            t1_rows.append([f"{nw}w", wall_str, urls_sec, speedup,
                            peak_mem, peak_active, avg_cpu])

        lines.append(md_table(t1_headers, t1_rows))
        lines.append("")

        # ── Table 2: Quality Summary ─────────────────────────────────
        lines.append("### Table 2: Quality Summary (per worker count)\n")
        t2_headers = ["Workers", "Avg DOM Elems", "Avg DOM KB",
                       "Avg Vis Text", "Avg Net Reqs",
                       "Pages OK", "HTTP Errors"]
        t2_rows = []
        for nw, meta, by_host in cfgs:
            dom_elems = []
            dom_sizes = []
            vis_texts = []
            net_reqs = []
            pages_ok = 0
            http_errors = 0

            for host in hosts_sorted:
                m = by_host.get(host, {})
                if not m:
                    continue
                de = m.get("dom_element_count", 0)
                ds = m.get("dom_size_bytes", 0)
                vt = m.get("visible_text_length", 0)
                nr = m.get("network_request_count", 0)
                dc = m.get("dom_complete_ms", -1)
                status = m.get("http_status", 0)

                dom_elems.append(de)
                dom_sizes.append(ds / 1024)
                vis_texts.append(vt)
                net_reqs.append(nr)
                if dc != -1:
                    pages_ok += 1
                if status and status != 200:
                    http_errors += 1

            total_urls = len(hosts_sorted)
            t2_rows.append([
                f"{nw}w",
                f"{statistics.mean(dom_elems):.0f}" if dom_elems else "—",
                f"{statistics.mean(dom_sizes):.1f}" if dom_sizes else "—",
                f"{statistics.mean(vis_texts):.0f}" if vis_texts else "—",
                f"{statistics.mean(net_reqs):.0f}" if net_reqs else "—",
                f"{pages_ok}/{total_urls}",
                str(http_errors),
            ])

        lines.append(md_table(t2_headers, t2_rows))
        lines.append("")

        # ── Table 3: Quality Delta vs Baseline ───────────────────────
        lines.append("### Table 3: Quality Delta vs Baseline (1w)\n")
        lines.append("Average percentage change across all URLs.\n")

        baseline_data = cfgs[0][2]  # first config is baseline

        t3_headers = ["Workers", "DOM Elems D%", "DOM Size D%",
                       "Vis Text D%", "Net Reqs D%",
                       "Pages OK", "Timing Slowdown"]
        t3_rows = []

        for i, (nw, meta, by_host) in enumerate(cfgs):
            if i == 0:
                total_urls = len(hosts_sorted)
                # Count pages OK for baseline
                pages_ok = sum(
                    1 for h in hosts_sorted
                    if baseline_data.get(h, {}).get("dom_complete_ms", -1) != -1
                )
                t3_rows.append([
                    f"{nw}w", "baseline", "baseline", "baseline",
                    "baseline", f"{pages_ok}/{total_urls}", "1.00x",
                ])
                continue

            dom_deltas = []
            size_deltas = []
            text_deltas = []
            net_deltas = []
            timing_ratios = []
            pages_ok = 0

            for host in hosts_sorted:
                bm = baseline_data.get(host, {})
                cm = by_host.get(host, {})
                if not bm or not cm:
                    continue

                for key, deltas in [
                    ("dom_element_count", dom_deltas),
                    ("dom_size_bytes", size_deltas),
                    ("visible_text_length", text_deltas),
                    ("network_request_count", net_deltas),
                ]:
                    bv = bm.get(key, 0)
                    cv = cm.get(key, 0)
                    if bv > 0:
                        deltas.append((cv - bv) / bv * 100)

                b_dc = bm.get("dom_complete_ms", -1)
                c_dc = cm.get("dom_complete_ms", -1)
                if c_dc != -1:
                    pages_ok += 1
                if b_dc > 0 and c_dc > 0:
                    timing_ratios.append(c_dc / b_dc)

            def _avg_delta(deltas):
                if not deltas:
                    return "—"
                avg = statistics.mean(deltas)
                return f"{avg:+.1f}%"

            total_urls = len(hosts_sorted)
            avg_timing = (
                f"{statistics.mean(timing_ratios):.2f}x"
                if timing_ratios else "—"
            )

            t3_rows.append([
                f"{nw}w",
                _avg_delta(dom_deltas),
                _avg_delta(size_deltas),
                _avg_delta(text_deltas),
                _avg_delta(net_deltas),
                f"{pages_ok}/{total_urls}",
                avg_timing,
            ])

        lines.append(md_table(t3_headers, t3_rows))
        lines.append("")

        # ── Table 4: Per-URL Quality Matrix ──────────────────────────
        lines.append("### Table 4: Per-URL Quality Matrix\n")
        lines.append("Status per URL at each concurrency level "
                      "(vs 1w baseline).\n")

        t4_headers = ["URL"] + [f"{nw}w" for nw in worker_counts]
        t4_rows = []

        for host in hosts_sorted:
            row = [host]
            bm = baseline_data.get(host, {})

            for j, (nw, meta, by_host) in enumerate(cfgs):
                cm = by_host.get(host, {})

                if j == 0:
                    # Baseline itself
                    dc = bm.get("dom_complete_ms", -1)
                    status = bm.get("http_status", 0)
                    if dc == -1 or (status and status not in (0, 200)):
                        row.append("FAILED")
                    else:
                        row.append("OK")
                    continue

                if not cm:
                    row.append("FAILED")
                    continue

                dc = cm.get("dom_complete_ms", -1)
                status = cm.get("http_status", 0)
                b_dc = bm.get("dom_complete_ms", -1)

                # Check FAILED first
                if dc == -1 or (status and status not in (0, 200)):
                    row.append("FAILED")
                    continue

                # Check DOM element deviation
                b_dom = bm.get("dom_element_count", 0)
                c_dom = cm.get("dom_element_count", 0)
                dom_pct = (
                    abs(c_dom - b_dom) / b_dom * 100
                    if b_dom > 0 else 0
                )

                if dom_pct > 10:
                    row.append("DEGRADED")
                    continue

                # Check WARN conditions: timing >2x or net requests dropped >20%
                timing_bad = (
                    b_dc > 0 and dc > 0 and dc > 2 * b_dc
                )
                b_net = bm.get("network_request_count", 0)
                c_net = cm.get("network_request_count", 0)
                net_dropped = (
                    b_net > 0 and (b_net - c_net) / b_net > 0.20
                )

                if dom_pct <= 5 and (timing_bad or net_dropped):
                    row.append("WARN")
                elif dom_pct <= 5:
                    row.append("OK")
                else:
                    # Between 5% and 10% — still OK but borderline
                    row.append("OK")

            t4_rows.append(row)

        lines.append(md_table(t4_headers, t4_rows))
        lines.append("")

        # ── Table 5: Detailed Degradation List ───────────────────────
        lines.append("### Table 5: Detailed Degradation List\n")
        lines.append("URLs with quality issues at any concurrency level.\n")

        t5_headers = ["URL", "Workers", "Issue", "Baseline",
                       "Actual", "Change%"]
        t5_rows = []

        check_keys = [
            ("dom_element_count", "DOM elements", 10),
            ("dom_size_bytes", "DOM size", 10),
            ("visible_text_length", "Visible text", 10),
            ("network_request_count", "Net requests", 15),
        ]

        for host in hosts_sorted:
            bm = baseline_data.get(host, {})
            if not bm:
                continue

            for i, (nw, meta, by_host) in enumerate(cfgs):
                if i == 0:
                    continue
                cm = by_host.get(host, {})
                if not cm:
                    t5_rows.append([
                        host, f"{nw}w", "Missing data", "—", "—", "—",
                    ])
                    continue

                for key, label, threshold in check_keys:
                    bv = bm.get(key, 0)
                    cv = cm.get(key, 0)
                    if bv and cv and bv > 0:
                        change = (cv - bv) / bv * 100
                        if abs(change) > threshold:
                            bv_display = (
                                f"{bv / 1024:.0f}KB"
                                if key == "dom_size_bytes"
                                else fmt(bv)
                            )
                            cv_display = (
                                f"{cv / 1024:.0f}KB"
                                if key == "dom_size_bytes"
                                else fmt(cv)
                            )
                            t5_rows.append([
                                host, f"{nw}w", label,
                                bv_display, cv_display, f"{change:+.0f}%",
                            ])

                # dom_complete going to -1
                b_dc = bm.get("dom_complete_ms", -1)
                c_dc = cm.get("dom_complete_ms", -1)
                if b_dc > 0 and c_dc == -1:
                    t5_rows.append([
                        host, f"{nw}w", "Page incomplete",
                        f"{b_dc:.0f}ms", "NEVER", "—",
                    ])

                # Timing slowdown >2x
                if b_dc > 0 and c_dc > 0 and c_dc > 2 * b_dc:
                    ratio = c_dc / b_dc
                    t5_rows.append([
                        host, f"{nw}w", "Timing >2x slower",
                        f"{b_dc:.0f}ms", f"{c_dc:.0f}ms",
                        f"{(ratio - 1) * 100:+.0f}%",
                    ])

                # HTTP status change
                b_status = bm.get("http_status", 0)
                c_status = cm.get("http_status", 0)
                if b_status != c_status and b_status > 0:
                    t5_rows.append([
                        host, f"{nw}w", f"HTTP {c_status}",
                        str(b_status), str(c_status), "status change",
                    ])

        if t5_rows:
            lines.append(md_table(t5_headers, t5_rows))
        else:
            lines.append("No degradation detected across any configuration.")
        lines.append("")

        # ── Table 6: Quality Score Breakdown ──────────────────────────
        lines.append("### Table 6: Quality Score Breakdown\n")
        lines.append("Composite score: 100 = identical to baseline, "
                      "lower = worse.\n")

        t6_headers = ["Workers", "DOM Score", "Content Score",
                       "Network Score", "Timing Score", "Overall"]
        t6_rows = []

        for i, (nw, meta, by_host) in enumerate(cfgs):
            dom_scores, content_scores = [], []
            net_scores, timing_scores = [], []

            for host in hosts_sorted:
                bm = baseline_data.get(host, {})
                cm = by_host.get(host, {})
                if not bm or not cm:
                    continue

                b = bm.get("dom_element_count", 0)
                c = cm.get("dom_element_count", 0)
                if b > 0:
                    dom_scores.append(
                        min(c / b, b / c) * 100 if c > 0 else 0
                    )

                b = bm.get("visible_text_length", 0)
                c = cm.get("visible_text_length", 0)
                if b > 0:
                    content_scores.append(
                        min(c / b, b / c) * 100 if c > 0 else 0
                    )

                b = bm.get("network_request_count", 0)
                c = cm.get("network_request_count", 0)
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
            overall = dom * 0.3 + content * 0.3 + net * 0.2 + timing * 0.2

            t6_rows.append([
                f"{nw}w",
                f"{dom:.1f}",
                f"{content:.1f}",
                f"{net:.1f}",
                f"{timing:.1f}",
                f"**{overall:.1f}**",
            ])

        lines.append(md_table(t6_headers, t6_rows))
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Scaling quality analysis — summary tables.",
    )
    parser.add_argument("job_dir", type=Path,
                        help="Scaling job directory")
    parser.add_argument("--baseline-job", type=Path, default=None,
                        help="Regular job directory to use as 1-worker baseline")
    args = parser.parse_args()

    if not args.job_dir.exists():
        print(f"Error: {args.job_dir} not found", file=sys.stderr)
        sys.exit(1)
    if args.baseline_job and not args.baseline_job.exists():
        print(f"Error: {args.baseline_job} not found", file=sys.stderr)
        sys.exit(1)

    report = generate_analysis(args.job_dir, baseline_job=args.baseline_job)

    out_path = args.job_dir / "scaling_analysis.md"
    out_path.write_text(report)
    print(report)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
