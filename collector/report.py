"""Generate summary report from comparison results."""

import csv
import json
from dataclasses import asdict
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .comparator import ComparisonResult

console = Console()


def _format_tag_diffs(diffs: dict[str, tuple[int, int]], limit: int = 10) -> str:
    """Format tag count diffs as 'tag: HL->HF' strings, sorted by abs diff."""
    if not diffs:
        return "-"
    sorted_diffs = sorted(diffs.items(), key=lambda x: abs(x[1][1] - x[1][0]), reverse=True)
    parts = [f"{tag}: {hl}->{hf}" for tag, (hl, hf) in sorted_diffs[:limit]]
    return ", ".join(parts)


def _format_req_diffs(diffs: dict[str, tuple[int, int]]) -> str:
    """Format request type diffs as 'type: HL->HF' strings."""
    if not diffs:
        return "-"
    sorted_diffs = sorted(diffs.items(), key=lambda x: abs(x[1][1] - x[1][0]), reverse=True)
    parts = [f"{rtype}: {hl}->{hf}" for rtype, (hl, hf) in sorted_diffs]
    return ", ".join(parts)


def generate_markdown_report(
    results: list[ComparisonResult],
    output_dir: Path,
) -> Path:
    """Write a markdown report sorted by severity."""
    results_sorted = sorted(results, key=lambda r: r.severity, reverse=True)

    # Discover which modes were compared
    compared_modes = sorted({r.compared_mode for r in results})

    report_path = output_dir / "report.md"
    lines: list[str] = []
    lines.append("# Rendering Comparison Report\n")
    lines.append(f"**Comparisons**: {len(results)}  ")
    lines.append(f"**Modes compared against headful**: {', '.join(compared_modes)}\n")

    sig_count = sum(1 for r in results if r.severity > 10)
    lines.append(f"**Significant differences (severity > 10)**: {sig_count}\n")

    # Category breakdown
    categories: dict[str, int] = {}
    for r in results:
        categories[r.diff_type] = categories.get(r.diff_type, 0) + 1
    lines.append("## Diff Categories\n")
    lines.append("| Category | Count |")
    lines.append("| --- | --- |")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        lines.append(f"| {cat} | {count} |")
    lines.append("")

    # Main results table
    lines.append("## Results (sorted by severity)\n")
    lines.append(
        "| Rank | Host | Mode | Severity | Type | Screenshot Diff | "
        "DOM Ratio | DOM Size Ratio | Content Ratio | Net Req Diff | "
        "Structural | Title | Redirect |"
    )
    lines.append(
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | "
        "--- | --- | --- |"
    )

    for r in results_sorted:
        struct = ", ".join(r.elements_only_headful) if r.elements_only_headful else "-"
        lines.append(
            f"| {r.rank} | {r.host} | {r.compared_mode} | {r.severity:.1f} | {r.diff_type} | "
            f"{r.screenshot_diff_pct:.1%} | {r.dom_count_ratio:+.2f} | "
            f"{r.dom_size_ratio:+.2f} | "
            f"{r.content_length_ratio:+.2f} | {r.network_request_diff:+d} | "
            f"{struct} | "
            f"{'Y' if r.has_title_diff else '-'} | "
            f"{'Y' if r.has_redirect_diff else '-'} |"
        )
    lines.append("")

    # Resource usage summary table
    has_resources = any(
        r.headless_peak_rss_mb > 0 or r.headful_peak_rss_mb > 0
        for r in results
    )
    if has_resources:
        lines.append("## Resource Usage (before screenshot)\n")
        lines.append(
            "| Rank | Host | Mode | Peak RSS (MB) | Peak USS (MB) | "
            "CPU Time (s) | Headful RSS (MB) | Headful USS (MB) | Headful CPU (s) |"
        )
        lines.append(
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
        )
        for r in results_sorted:
            lines.append(
                f"| {r.rank} | {r.host} | {r.compared_mode} | "
                f"{r.headless_peak_rss_mb:.1f} | {r.headless_peak_uss_mb:.1f} | "
                f"{r.headless_cpu_time_s:.2f} | "
                f"{r.headful_peak_rss_mb:.1f} | {r.headful_peak_uss_mb:.1f} | "
                f"{r.headful_cpu_time_s:.2f} |"
            )
        lines.append("")

        lines.append("## Resource Usage (after screenshot)\n")
        lines.append(
            "| Rank | Host | Mode | RSS (MB) | USS (MB) | "
            "CPU incl. SS (s) | Headful RSS (MB) | Headful USS (MB) | Headful CPU incl. SS (s) |"
        )
        lines.append(
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
        )
        for r in results_sorted:
            lines.append(
                f"| {r.rank} | {r.host} | {r.compared_mode} | "
                f"{r.headless_rss_after_screenshot_mb:.1f} | {r.headless_uss_after_screenshot_mb:.1f} | "
                f"{r.headless_cpu_time_with_screenshot_s:.2f} | "
                f"{r.headful_rss_after_screenshot_mb:.1f} | {r.headful_uss_after_screenshot_mb:.1f} | "
                f"{r.headful_cpu_time_with_screenshot_s:.2f} |"
            )
        lines.append("")

    # Detailed per-URL sections for URLs with significant diffs
    sig_results = [r for r in results_sorted if r.severity > 10]
    if sig_results:
        lines.append("## Detailed Diffs\n")
        for r in sig_results:
            lines.append(f"### {r.host} (rank {r.rank}, {r.compared_mode} vs headful, severity {r.severity:.1f})\n")
            lines.append(f"- **Type**: {r.diff_type}")
            lines.append(f"- **Screenshot diff**: {r.screenshot_diff_pct:.1%}")
            lines.append(f"- **DOM ratio** (log2 headful/{r.compared_mode}): {r.dom_count_ratio:+.2f}")
            lines.append(f"- **DOM size ratio** (log2 headful/{r.compared_mode}): {r.dom_size_ratio:+.2f}")
            lines.append(
                f"- **Content ratio** (log2 headful/{r.compared_mode}): "
                f"{r.content_length_ratio:+.2f}"
            )
            lines.append(f"- **Network requests**: {r.network_request_diff:+d}")
            if r.elements_only_headful:
                lines.append(
                    f"- **Elements only in headful**: {', '.join(r.elements_only_headful)}"
                )
            if r.elements_only_headless:
                lines.append(
                    f"- **Elements only in {r.compared_mode}**: {', '.join(r.elements_only_headless)}"
                )
            if r.tag_count_diffs:
                lines.append(
                    f"- **Top tag diffs** ({r.compared_mode}->headful): "
                    f"{_format_tag_diffs(r.tag_count_diffs)}"
                )
            if r.request_type_diffs:
                lines.append(
                    f"- **Request type diffs** ({r.compared_mode}->headful): "
                    f"{_format_req_diffs(r.request_type_diffs)}"
                )
            if r.has_title_diff:
                lines.append("- **Title differs**")
            if r.has_redirect_diff:
                lines.append("- **Redirect differs**")
            if r.headless_peak_rss_mb > 0 or r.headful_peak_rss_mb > 0:
                lines.append(
                    f"- **Resource usage before screenshot** ({r.compared_mode}): "
                    f"RSS {r.headless_peak_rss_mb:.1f} MB, "
                    f"USS {r.headless_peak_uss_mb:.1f} MB, "
                    f"CPU {r.headless_cpu_time_s:.2f}s"
                )
                lines.append(
                    f"- **Resource usage before screenshot** (headful): "
                    f"RSS {r.headful_peak_rss_mb:.1f} MB, "
                    f"USS {r.headful_peak_uss_mb:.1f} MB, "
                    f"CPU {r.headful_cpu_time_s:.2f}s"
                )
                lines.append(
                    f"- **Resource usage after screenshot** ({r.compared_mode}): "
                    f"RSS {r.headless_rss_after_screenshot_mb:.1f} MB, "
                    f"USS {r.headless_uss_after_screenshot_mb:.1f} MB, "
                    f"CPU {r.headless_cpu_time_with_screenshot_s:.2f}s"
                )
                lines.append(
                    f"- **Resource usage after screenshot** (headful): "
                    f"RSS {r.headful_rss_after_screenshot_mb:.1f} MB, "
                    f"USS {r.headful_uss_after_screenshot_mb:.1f} MB, "
                    f"CPU {r.headful_cpu_time_with_screenshot_s:.2f}s"
                )
            if r.headless_error:
                lines.append(f"- **{r.compared_mode} error**: {r.headless_error}")
            if r.headful_error:
                lines.append(f"- **Headful error**: {r.headful_error}")
            lines.append("")

    report_path.write_text("\n".join(lines))
    return report_path


def generate_csv(results: list[ComparisonResult], output_dir: Path) -> Path:
    """Write a CSV of all results for further analysis."""
    csv_path = output_dir / "results.csv"
    fieldnames = [
        "rank",
        "host",
        "url",
        "compared_mode",
        "severity",
        "diff_type",
        "screenshot_diff_pct",
        "dom_count_ratio",
        "dom_size_ratio",
        "content_length_ratio",
        "network_request_diff",
        "has_structural_diff",
        "has_title_diff",
        "has_redirect_diff",
        "elements_only_headful",
        "elements_only_headless",
        "tag_count_diffs",
        "request_type_diffs",
        "headless_console_errors",
        "headful_console_errors",
        "headless_error",
        "headful_error",
        "resource_count_diff",
        "transfer_bytes_diff",
        "document_height_diff",
        "document_width_diff",
        "headless_peak_rss_mb",
        "headless_peak_uss_mb",
        "headless_cpu_time_s",
        "headless_cpu_time_with_screenshot_s",
        "headless_rss_after_screenshot_mb",
        "headless_uss_after_screenshot_mb",
        "headful_peak_rss_mb",
        "headful_peak_uss_mb",
        "headful_cpu_time_s",
        "headful_cpu_time_with_screenshot_s",
        "headful_rss_after_screenshot_mb",
        "headful_uss_after_screenshot_mb",
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in sorted(results, key=lambda r: r.severity, reverse=True):
            row = asdict(r)
            row["elements_only_headful"] = ";".join(row["elements_only_headful"])
            row["elements_only_headless"] = ";".join(row["elements_only_headless"])
            row["tag_count_diffs"] = json.dumps(row["tag_count_diffs"])
            row["request_type_diffs"] = json.dumps(row["request_type_diffs"])
            writer.writerow({k: row[k] for k in fieldnames})
    return csv_path


def save_raw_metrics(all_metrics: list[dict], output_dir: Path) -> Path:
    """Save the raw per-URL metrics as JSON for later analysis."""
    path = output_dir / "raw_metrics.json"
    path.write_text(json.dumps(all_metrics, indent=2, default=str))
    return path


def print_summary(results: list[ComparisonResult]) -> None:
    """Print a rich table summary to console."""
    table = Table(title="Rendering Comparison Summary", show_lines=True)
    table.add_column("Rank", style="dim", justify="right")
    table.add_column("Host", style="cyan")
    table.add_column("Mode", justify="center")
    table.add_column("Severity", justify="right", style="bold")
    table.add_column("Type", justify="center")
    table.add_column("Screenshot %", justify="right")
    table.add_column("DOM Ratio", justify="right")
    table.add_column("DOM Size", justify="right")
    table.add_column("Net Req", justify="right")
    table.add_column("RSS (MB)", justify="right")
    table.add_column("CPU (s)", justify="right")
    table.add_column("CPU+SS (s)", justify="right")
    table.add_column("RSS post-SS", justify="right")

    for r in sorted(results, key=lambda x: x.severity, reverse=True)[:30]:
        sev_style = (
            "bold red" if r.severity > 20 else ("yellow" if r.severity > 10 else "dim")
        )
        rss_str = (
            f"{r.headless_peak_rss_mb:.0f}/{r.headful_peak_rss_mb:.0f}"
            if r.headless_peak_rss_mb > 0 or r.headful_peak_rss_mb > 0
            else "-"
        )
        cpu_str = (
            f"{r.headless_cpu_time_s:.1f}/{r.headful_cpu_time_s:.1f}"
            if r.headless_cpu_time_s > 0 or r.headful_cpu_time_s > 0
            else "-"
        )
        cpu_ss_str = (
            f"{r.headless_cpu_time_with_screenshot_s:.1f}/{r.headful_cpu_time_with_screenshot_s:.1f}"
            if r.headless_cpu_time_with_screenshot_s > 0 or r.headful_cpu_time_with_screenshot_s > 0
            else "-"
        )
        rss_post_str = (
            f"{r.headless_rss_after_screenshot_mb:.0f}/{r.headful_rss_after_screenshot_mb:.0f}"
            if r.headless_rss_after_screenshot_mb > 0 or r.headful_rss_after_screenshot_mb > 0
            else "-"
        )
        table.add_row(
            str(r.rank),
            r.host,
            r.compared_mode,
            f"[{sev_style}]{r.severity:.1f}[/{sev_style}]",
            r.diff_type,
            f"{r.screenshot_diff_pct:.1%}",
            f"{r.dom_count_ratio:+.2f}",
            f"{r.dom_size_ratio:+.2f}",
            f"{r.network_request_diff:+d}",
            rss_str,
            cpu_str,
            cpu_ss_str,
            rss_post_str,
        )
    console.print(table)
