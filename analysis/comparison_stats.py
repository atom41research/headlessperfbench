#!/usr/bin/env python3
"""Generate comprehensive_stats.md from a job's raw_metrics.json and results.csv.

Moved from generate_stats.py at project root into the analysis package.
Uses shared percentile() and compute_stats() from analysis.utils.
"""

import csv
import json
import statistics
import sys
from pathlib import Path

from .utils import compute_stats, percentile


MODES = ["headful", "headless", "headless-shell"]
STAT_ROWS = ["avg", "std", "min", "p25", "median", "p75", "max"]


def ratio_str(a, b):
    if b == 0:
        return "inf"
    return f"{a / b:.2f}x"


def write_detail_header(lines):
    lines.append("| Metric                         | Stat     |          headful |         headless |   headless-shell |")
    lines.append("|--------------------------------|----------|------------------|------------------|------------------|")


def write_metric_block(lines, label, n, mode_stats, fmt_fn):
    """Write one metric block: 7 stat rows + ratio row + blank separator."""
    lines.append(
        f"| **{label}** (n={n}) | avg      | "
        + " | ".join(f"{fmt_fn(mode_stats[m]['avg']):>16}" for m in MODES)
        + " |"
    )
    for stat in STAT_ROWS[1:]:
        lines.append(
            f"|                                | {stat:<8} | "
            + " | ".join(f"{fmt_fn(mode_stats[m][stat]):>16}" for m in MODES)
            + " |"
        )
    base_avg = mode_stats["headful"]["avg"]
    ratios = []
    for m in MODES:
        if m == "headful":
            ratios.append(f"{'**1.00x**':>16}")
        else:
            r = base_avg / mode_stats[m]["avg"] if mode_stats[m]["avg"] != 0 else float("inf")
            ratios.append(f"{'**' + f'{r:.2f}x' + '**':>16}")
    lines.append(
        f"|                                | **ratio** | " + " | ".join(ratios) + " |"
    )
    lines.append("|                                |          |                  |                  |                  |")


def write_averages_table(lines, title, n, metrics_list):
    """Write a compact averages table: Headless | Headful | Shell."""
    lines.append(f"### {title} — Averages (n={n})\n")
    lines.append("| Metric                         |   Headless |   Headful |   Shell |")
    lines.append("|--------------------------------|-----------:|----------:|--------:|")
    for label, ms in metrics_list:
        hl = ms["headless"]["avg"]
        hf = ms["headful"]["avg"]
        hs = ms["headless-shell"]["avg"]
        lines.append(
            f"| {label:<30} | {hl:>10.1f} | {hf:>9.1f} | {hs:>7.1f} |"
        )


def write_ratios_table(lines, title, metrics_list):
    """Write a compact ratios table: HF/HL | HF/Shell — same rows as averages."""
    lines.append(f"\n### {title} — Overhead Ratios\n")
    lines.append("Higher ratio = headful uses more of that resource.\n")
    lines.append("| Metric                         |   HF/HL |   HF/Shell |")
    lines.append("|--------------------------------|--------:|-----------:|")
    for label, ms in metrics_list:
        hf = ms["headful"]["avg"]
        hl = ms["headless"]["avg"]
        hs = ms["headless-shell"]["avg"]
        lines.append(
            f"| {label:<30} | {ratio_str(hf, hl):>7} | {ratio_str(hf, hs):>10} |"
        )


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python -m analysis stats <job_dir>")
        print("\nGenerate comprehensive 3-mode comparison statistics report.")
        print("Reads raw_metrics.json and results.csv from <job_dir>.")
        print("Outputs comprehensive_stats.md in the same directory.")
        sys.exit(0 if len(sys.argv) >= 2 else 1)

    job_dir = Path(sys.argv[1])
    raw_path = job_dir / "raw_metrics.json"
    csv_path = job_dir / "results.csv"

    raw_data = json.loads(raw_path.read_text())
    total_urls = len(raw_data)

    # ── Helpers ───────────────────────────────────────────────────────────
    def mode_ok(entry, mode):
        m = entry.get(mode, {})
        return m and not m.get("error")

    def get_val(entry, mode, key, default=None):
        return entry.get(mode, {}).get(key, default)

    def collect(key, filter_fn=None):
        """Collect per-mode values, requiring ALL modes ok."""
        result = {m: [] for m in MODES}
        for entry in raw_data:
            if not all(mode_ok(entry, m) for m in MODES):
                continue
            if filter_fn and not filter_fn(entry):
                continue
            for m in MODES:
                v = get_val(entry, m, key)
                if v is not None:
                    result[m].append(v)
        return result

    def stats_for(d):
        return {m: compute_stats(d[m]) for m in MODES}

    def make_delta(a_dict, b_dict):
        result = {m: [] for m in MODES}
        for m in MODES:
            for av, bv in zip(a_dict[m], b_dict[m]):
                result[m].append(bv - av)
        return result

    # ── Collect all metrics ───────────────────────────────────────────────

    # Performance: Chrome process tree
    cpu_before = collect("cpu_time_s")
    cpu_incl_ss = collect("cpu_time_with_screenshot_s")
    peak_rss = collect("peak_rss_mb")
    rss_after = collect("rss_after_screenshot_mb")
    peak_uss = collect("peak_uss_mb")
    uss_after = collect("uss_after_screenshot_mb")
    chrome_avg_rss = collect("chrome_avg_rss_mb")
    chrome_avg_uss = collect("chrome_avg_uss_mb")
    chrome_cpu_pct_avg = collect("chrome_cpu_pct_avg")
    chrome_cpu_pct_peak = collect("chrome_cpu_pct_peak")
    process_count_peak = collect("process_count_peak")

    # Performance: Container cgroup
    container_active_mem = collect("container_active_memory_mb")
    container_total_mem = collect("container_total_memory_mb")
    container_cpu_pct = collect("container_cpu_pct")

    # Deltas
    cpu_ss_delta = make_delta(cpu_before, cpu_incl_ss)
    rss_ss_delta = make_delta(peak_rss, rss_after)
    uss_ss_delta = make_delta(peak_uss, uss_after)

    # Quality: DOM & Content
    dom_count = collect("dom_element_count")
    dom_size = collect("dom_size_bytes")
    visible_text = collect("visible_text_length",
                           lambda e: all(get_val(e, m, "visible_text_length", 0) > 0 for m in MODES))

    def collect_computed(fn):
        result = {m: [] for m in MODES}
        for entry in raw_data:
            if not all(mode_ok(entry, m) for m in MODES):
                continue
            for m in MODES:
                result[m].append(fn(entry, m))
        return result

    tag_types = collect_computed(lambda e, m: len(get_val(e, m, "tag_counts", {})))
    structural = collect_computed(
        lambda e, m: sum(1 for v in get_val(e, m, "structural_present", {}).values() if v)
    )

    # Quality: Network
    net_requests = collect("network_request_count")
    req_variety = collect_computed(
        lambda e, m: len(get_val(e, m, "request_counts_by_type", {}))
    )
    http_status = collect("http_status")
    console_errors = collect_computed(
        lambda e, m: len(get_val(e, m, "console_errors", []))
    )

    # Flags
    has_enhanced = len(chrome_avg_rss["headful"]) > 0 and any(v > 0 for v in chrome_avg_rss["headful"])
    has_container = len(container_active_mem["headful"]) > 0 and any(v > 0 for v in container_active_mem["headful"])

    n_resource = len(cpu_before["headful"])
    n_dom = len(dom_count["headful"])
    n_vis = len(visible_text["headful"])

    # ── Generate markdown ────────────────────────────────────────────────
    lines = []
    lines.append(f"# Comprehensive 3-Mode Statistics — {total_urls} URLs\n")
    lines.append("---\n")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PERFORMANCE
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    lines.append("## Performance Metrics\n")

    # -- Summary tables --
    perf_summary = []
    if has_container:
        perf_summary.append(("Container Active Memory (MB)", stats_for(container_active_mem)))
        perf_summary.append(("Container CPU%", stats_for(container_cpu_pct)))
    if has_enhanced:
        perf_summary.append(("Chrome USS (MB)", stats_for(chrome_avg_uss)))
        perf_summary.append(("Chrome USS peak (MB)", stats_for(peak_uss)))
        perf_summary.append(("Chrome RSS (MB)", stats_for(chrome_avg_rss)))
        perf_summary.append(("Chrome CPU% (avg)", stats_for(chrome_cpu_pct_avg)))
        perf_summary.append(("Chrome CPU% (peak)", stats_for(chrome_cpu_pct_peak)))
        perf_summary.append(("Process count (peak)", stats_for(process_count_peak)))
    else:
        perf_summary.append(("Chrome USS peak (MB)", stats_for(peak_uss)))
        perf_summary.append(("Chrome RSS peak (MB)", stats_for(peak_rss)))
        perf_summary.append(("Chrome CPU Time (s)", stats_for(cpu_before)))

    write_averages_table(lines, "Performance", n_resource, perf_summary)
    lines.append("")
    write_ratios_table(lines, "Performance", perf_summary)

    # -- Full detail tables --
    lines.append("")
    lines.append("### Performance — Full Detail\n")
    write_detail_header(lines)

    if has_container:
        write_metric_block(lines, "Container Active Memory (MB)", n_resource, stats_for(container_active_mem), lambda v: f"{v:.0f}")
        write_metric_block(lines, "Container CPU%", n_resource, stats_for(container_cpu_pct), lambda v: f"{v:.1f}")

    if has_enhanced:
        write_metric_block(lines, "Chrome RSS (MB)", n_resource, stats_for(chrome_avg_rss), lambda v: f"{v:.0f}")
        write_metric_block(lines, "Chrome USS (MB)", n_resource, stats_for(chrome_avg_uss), lambda v: f"{v:.0f}")
        write_metric_block(lines, "Chrome CPU% (avg)", n_resource, stats_for(chrome_cpu_pct_avg), lambda v: f"{v:.1f}")
        write_metric_block(lines, "Chrome CPU% (peak)", n_resource, stats_for(chrome_cpu_pct_peak), lambda v: f"{v:.1f}")
        write_metric_block(lines, "Process count (peak)", n_resource, stats_for(process_count_peak), lambda v: f"{v:.0f}")

    write_metric_block(lines, "Peak RSS before SS (MB)", n_resource, stats_for(peak_rss), lambda v: f"{v:.0f}")
    write_metric_block(lines, "RSS after SS (MB)", n_resource, stats_for(rss_after), lambda v: f"{v:.0f}")
    write_metric_block(lines, "RSS SS delta (MB)", n_resource, stats_for(rss_ss_delta), lambda v: f"{v:.1f}")
    write_metric_block(lines, "Peak USS before SS (MB)", n_resource, stats_for(peak_uss), lambda v: f"{v:.0f}")
    write_metric_block(lines, "USS after SS (MB)", n_resource, stats_for(uss_after), lambda v: f"{v:.0f}")
    write_metric_block(lines, "USS SS delta (MB)", n_resource, stats_for(uss_ss_delta), lambda v: f"{v:.1f}")
    write_metric_block(lines, "CPU Time before SS (s)", n_resource, stats_for(cpu_before), lambda v: f"{v:.2f}")
    write_metric_block(lines, "CPU Time incl. SS (s)", n_resource, stats_for(cpu_incl_ss), lambda v: f"{v:.2f}")
    write_metric_block(lines, "CPU SS delta (s)", n_resource, stats_for(cpu_ss_delta), lambda v: f"{v:.2f}")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # QUALITY
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    lines.append("")
    lines.append("## Quality Metrics\n")

    # -- Summary tables --
    quality_summary = [
        ("DOM Element Count", stats_for(dom_count)),
        ("DOM Size (bytes)", stats_for(dom_size)),
        ("Visible Text Length", stats_for(visible_text)),
        ("Unique Tag Types", stats_for(tag_types)),
        ("Structural Elements", stats_for(structural)),
        ("Network Requests", stats_for(net_requests)),
        ("Request Type Variety", stats_for(req_variety)),
        ("HTTP Status", stats_for(http_status)),
        ("Console Errors", stats_for(console_errors)),
    ]

    write_averages_table(lines, "Quality", n_dom, quality_summary)
    lines.append("")
    write_ratios_table(lines, "Quality", quality_summary)

    # -- Full detail tables --
    lines.append("")
    lines.append("### Quality — Full Detail\n")
    write_detail_header(lines)

    write_metric_block(lines, "DOM Element Count", n_dom, stats_for(dom_count), lambda v: f"{v:.0f}")
    write_metric_block(lines, "DOM Size (bytes)", n_dom, stats_for(dom_size), lambda v: f"{v:.0f}")
    write_metric_block(lines, "Visible Text Length", n_vis, stats_for(visible_text), lambda v: f"{v:.0f}")
    write_metric_block(lines, "Unique Tag Types", n_dom, stats_for(tag_types), lambda v: f"{v:.0f}")
    write_metric_block(lines, "Structural Elements", n_dom, stats_for(structural), lambda v: f"{v:.1f}")
    write_metric_block(lines, "Network Requests", n_dom, stats_for(net_requests), lambda v: f"{v:.0f}")
    write_metric_block(lines, "Request Type Variety", n_dom, stats_for(req_variety), lambda v: f"{v:.0f}")
    write_metric_block(lines, "HTTP Status", n_dom, stats_for(http_status), lambda v: f"{v:.0f}")
    write_metric_block(lines, "Console Errors", n_dom, stats_for(console_errors), lambda v: f"{v:.1f}")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # RENDERING FIDELITY
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    with open(csv_path) as f:
        csv_rows = list(csv.DictReader(f))

    by_mode = {}
    for row in csv_rows:
        by_mode.setdefault(row["compared_mode"], []).append(row)

    lines.append("")
    lines.append("## Rendering Fidelity\n")

    for cm in ["headless", "headless-shell"]:
        rows = by_mode.get(cm, [])
        if not rows:
            continue
        n_total = len(rows)
        sig = sum(1 for r in rows if float(r["severity"]) > 10)

        cats = {}
        for r in rows:
            cats[r["diff_type"]] = cats.get(r["diff_type"], 0) + 1
        cat_str = ", ".join(f"{k}={v}" for k, v in sorted(cats.items(), key=lambda x: -x[1]))

        lines.append(f"### {cm} vs headful (n={n_total})\n")
        lines.append(f"- Significant diffs (severity > 10): **{sig}/{n_total} ({sig*100//n_total}%)**")
        lines.append(f"- Categories: {cat_str}\n")

        sev = [float(r["severity"]) for r in rows]
        ss_diff = [float(r["screenshot_diff_pct"]) for r in rows]
        dom_cr = [float(r["dom_count_ratio"]) for r in rows]
        dom_sr = [float(r["dom_size_ratio"]) for r in rows]
        cl_r = [float(r["content_length_ratio"]) for r in rows]
        net_rd = [int(float(r["network_request_diff"])) for r in rows]

        fid_metrics = [
            ("Severity", sev, lambda v: f"{v:.1f}"),
            ("Screenshot Diff %", ss_diff, lambda v: f"{v:.4f}"),
            ("DOM Count Ratio (log2)", dom_cr, lambda v: f"{v:.3f}"),
            ("DOM Size Ratio (log2)", dom_sr, lambda v: f"{v:.3f}"),
            ("Content Length Ratio (log2)", cl_r, lambda v: f"{v:.3f}"),
            ("Network Request Diff", net_rd, lambda v: f"{v:.0f}"),
        ]

        lines.append("| Metric                         |        avg |        std |        min |        p25 |     median |        p75 |        max |")
        lines.append("|--------------------------------|------------|------------|------------|------------|------------|------------|------------|")

        for label, vals, fmt in fid_metrics:
            st = compute_stats(vals)
            lines.append(
                f"| {label:<30} | {fmt(st['avg']):>10} | {fmt(st['std']):>10} | "
                f"{fmt(st['min']):>10} | {fmt(st['p25']):>10} | {fmt(st['median']):>10} | "
                f"{fmt(st['p75']):>10} | {fmt(st['max']):>10} |"
            )
        lines.append("")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ERRORS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    lines.append("## Errors\n")
    lines.append("| Mode             |   Count | Details                                                                          |")
    lines.append("|------------------|---------|----------------------------------------------------------------------------------|")

    for m in MODES:
        errors = []
        for entry in raw_data:
            md = entry.get(m, {})
            err = md.get("error", "")
            if err:
                first_line = err.split("\n")[0][:80]
                errors.append(first_line)
        seen = {}
        for e in errors:
            seen[e] = seen.get(e, 0) + 1
        unique_errors = [f"{e} (x{c})" if c > 1 else e for e, c in seen.items()]
        detail_str = "; ".join(unique_errors[:5])
        if len(unique_errors) > 5:
            detail_str += f"; ... (+{len(unique_errors)-5} more)"
        lines.append(f"| {m:<16} | {len(errors):>7} | {detail_str} |")

    lines.append("")

    out_path = job_dir / "comprehensive_stats.md"
    out_path.write_text("\n".join(lines))
    print(f"Written to {out_path}")


if __name__ == "__main__":
    main()
