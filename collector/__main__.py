"""Entry point: uv run python -m collector

Pipeline: parse ranked URLs -> visit in all requested modes -> compare against headful -> report.
"""

import asyncio
import gc
import json
import traceback
from dataclasses import asdict, fields
from pathlib import Path

from playwright.async_api import async_playwright
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    MofNCompleteColumn,
)

from . import config
from .parser import parse_ranking_file, parse_csv_results, parse_url_list
from .collector import collect_page_data, PageMetrics
from .comparator import compare, ComparisonResult, MODE_ABBREV
from .report import (
    generate_markdown_report,
    generate_csv,
    save_raw_metrics,
    print_summary,
)

console = Console()

# Reverse lookup: abbreviation -> mode name
_ABBREV_TO_MODE = {v: k for k, v in MODE_ABBREV.items()}


def _load_per_mode_json(output_dir: Path, mode: str) -> list[dict]:
    """Load per-mode metrics from JSONL (preferred) or JSON (legacy) file."""
    jsonl_path = output_dir / f"raw_metrics_{mode}.jsonl"
    json_path = output_dir / f"raw_metrics_{mode}.json"
    if jsonl_path.exists():
        entries = []
        for line in jsonl_path.read_text().splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries
    if json_path.exists():
        return json.loads(json_path.read_text())
    return []


def _jsonl_to_json(output_dir: Path, mode: str) -> None:
    """Convert a JSONL file to JSON array for backward compatibility."""
    jsonl_path = output_dir / f"raw_metrics_{mode}.jsonl"
    json_path = output_dir / f"raw_metrics_{mode}.json"
    if jsonl_path.exists():
        entries = _load_per_mode_json(output_dir, mode)
        json_path.write_text(json.dumps(entries, indent=2, default=str))


def _parse_diff_pairs(diff_pairs_str: str | None) -> set[tuple[str, str]]:
    """Parse 'HL-HF,HS-HF' into {('headless','headful'), ('headless-shell','headful')}."""
    if not diff_pairs_str:
        return set()
    pairs: set[tuple[str, str]] = set()
    for pair in diff_pairs_str.split(","):
        parts = pair.strip().split("-", 1)
        if len(parts) != 2:
            console.print(f"[red]Invalid diff pair '{pair}'. Use format like 'HL-HF'.[/red]")
            continue
        a_abbrev, b_abbrev = parts[0].strip(), parts[1].strip()
        a_mode = _ABBREV_TO_MODE.get(a_abbrev)
        b_mode = _ABBREV_TO_MODE.get(b_abbrev)
        if not a_mode or not b_mode:
            valid = ", ".join(f"{v}={k}" for k, v in MODE_ABBREV.items())
            console.print(f"[red]Unknown abbreviation in '{pair}'. Valid: {valid}[/red]")
            continue
        pairs.add((a_mode, b_mode))
    return pairs


# Per-mode timeout: page timeout + settle + screenshot + close overhead
_MODE_TIMEOUT_S = 60


async def process_url(
    pw, ranked_url, output_dir: Path, modes: list[str]
) -> dict[str, PageMetrics]:
    """Collect page metrics for every requested mode."""
    host_slug = ranked_url.host.replace(".", "_")
    results: dict[str, PageMetrics] = {}
    for mode in modes:
        try:
            results[mode] = await asyncio.wait_for(
                collect_page_data(
                    pw, ranked_url.url, mode, output_dir, host_slug,
                    rank=ranked_url.rank,
                ),
                timeout=_MODE_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            console.print(
                f"\n[yellow]Timeout: {ranked_url.host} [{mode}] after {_MODE_TIMEOUT_S}s[/yellow]"
            )
            results[mode] = PageMetrics(
                url=ranked_url.url,
                mode=mode,
                error=f"Mode timed out after {_MODE_TIMEOUT_S}s",
            )
    return results


def _dict_to_page_metrics(d: dict) -> PageMetrics:
    """Reconstruct a PageMetrics from a raw dict (JSON round-trip safe)."""
    valid_fields = {f.name for f in fields(PageMetrics)}
    filtered = {k: v for k, v in d.items() if k in valid_fields}
    return PageMetrics(**filtered)


def _parse_urls(args):
    """Parse URLs from the configured input source."""
    if args.url_list:
        urls = parse_url_list(
            args.url_list,
            top_n=args.top_n,
            start_rank=args.start_rank,
        )
        input_label = str(args.url_list)
        filter_label = f"url-list ({len(urls)} URLs)"
    elif args.csv_input:
        urls = parse_csv_results(
            args.csv_input,
            diff_types=args.filter_diff_types,
            min_net_req_diff=args.min_net_req_diff,
        )
        input_label = str(args.csv_input)
        filter_label = f"csv-input ({len(urls)} filtered URLs)"
    else:
        top_n = args.top_n if args.top_n is not None else config.DEFAULT_TOP_N
        full_better = args.full_better and not args.all_urls
        urls = parse_ranking_file(
            args.input,
            top_n=top_n,
            start_rank=args.start_rank,
            full_better_only=full_better,
        )
        input_label = str(args.input)
        filter_label = "full-better only" if full_better else "all"
    return urls, input_label, filter_label


def _merge_report(args):
    """Load per-mode raw_metrics_{mode}.json files, merge, compare, report."""
    output_dir: Path = args.output
    modes = args.modes.split(",")
    target_modes = [m for m in modes if m != "headful"]
    diff_pairs = _parse_diff_pairs(getattr(args, "diff_pairs", None))

    if "headful" not in modes:
        console.print("[red]headful mode is required as baseline for merge[/red]")
        return

    console.print("\n[bold]Merge Report[/bold]")
    console.print(f"Output dir: {output_dir}")
    console.print(f"Modes: {', '.join(modes)}")
    if diff_pairs:
        labels = ", ".join(
            f"{MODE_ABBREV[a]}-{MODE_ABBREV[b]}" for a, b in diff_pairs
        )
        console.print(f"Diff pairs: {labels}")
    console.print()

    # Load per-mode files (JSONL or legacy JSON)
    per_mode_data: dict[str, list[dict]] = {}
    for mode in modes:
        entries = _load_per_mode_json(output_dir, mode)
        if not entries:
            console.print(f"[red]Missing: raw_metrics_{mode}.jsonl / .json[/red]")
            return
        per_mode_data[mode] = entries
        console.print(f"  Loaded {mode}: {len(entries)} entries")

    # Index by (host, rank) for each mode
    mode_index: dict[str, dict[tuple[str, int], dict]] = {}
    for mode, entries in per_mode_data.items():
        idx: dict[tuple[str, int], dict] = {}
        for entry in entries:
            key = (entry["host"], entry["rank"])
            if mode in entry:
                idx[key] = entry[mode]
        mode_index[mode] = idx

    # Find URLs present in all modes
    all_keys = set(mode_index[modes[0]].keys())
    for mode in modes[1:]:
        all_keys &= set(mode_index[mode].keys())
    console.print(f"\n  URLs present in all modes: {len(all_keys)}")

    # Build comparisons
    all_comparisons: list[ComparisonResult] = []
    all_raw_metrics: list[dict] = []

    for host, rank in sorted(all_keys, key=lambda k: k[1]):
        metric_entry: dict = {"host": host, "rank": rank}
        mode_metrics: dict[str, PageMetrics] = {}
        for mode in modes:
            raw = mode_index[mode][(host, rank)]
            mode_metrics[mode] = _dict_to_page_metrics(raw)
            metric_entry[mode] = raw
        all_raw_metrics.append(metric_entry)

        headful_metrics = mode_metrics["headful"]
        for target_mode in target_modes:
            should_diff = (target_mode, "headful") in diff_pairs
            comparison = compare(
                mode_metrics[target_mode],
                headful_metrics,
                host=host,
                rank=rank,
                screenshots_dir=output_dir / "screenshots",
                generate_diff=should_diff,
            )
            comparison.compared_mode = target_mode
            all_comparisons.append(comparison)

    # Save merged raw metrics and reports
    save_raw_metrics(all_raw_metrics, output_dir)

    console.print("\n[bold]Generating reports...[/bold]")
    if all_comparisons:
        md_path = generate_markdown_report(all_comparisons, output_dir)
        csv_path = generate_csv(all_comparisons, output_dir)
        console.print(f"  Markdown: {md_path}")
        console.print(f"  CSV: {csv_path}")
        print_summary(all_comparisons)
    else:
        console.print("[yellow]No comparisons generated.[/yellow]")

    console.print("\n[bold green]Done.[/bold green]\n")


async def _collect_only(args):
    """Collect data for specified modes only — no comparison step."""
    modes = args.modes.split(",")
    invalid = [m for m in modes if m not in config.MODE_CONFIG]
    if invalid:
        console.print(f"[red]Unknown modes: {', '.join(invalid)}. "
                       f"Choose from: {', '.join(config.MODE_CONFIG)}[/red]")
        return

    # Scaling path (any worker count, including 1)
    if args.workers >= 1:
        from .scaling import run_scaling_test, save_scaling_output

        output_dir: Path = args.output
        urls, input_label, filter_label = _parse_urls(args)
        console.print(f"\n[bold]Scaling Collection — {args.workers} worker{'s' if args.workers > 1 else ''}[/bold]")
        console.print(f"Input: {input_label}")
        console.print(f"Filter: {filter_label}")
        console.print(f"URLs: {len(urls)}  |  Modes: {', '.join(modes)}")
        for mode in modes:
            result = run_scaling_test(mode, args.workers, urls, output_dir)
            save_scaling_output(result, output_dir)
        console.print("\n[bold green]Scaling collection complete.[/bold green]\n")
        return

    output_dir: Path = args.output
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "screenshots").mkdir(exist_ok=True)
    (output_dir / "har").mkdir(exist_ok=True)

    urls, input_label, filter_label = _parse_urls(args)

    console.print("\n[bold]Rendering Comparison — Collect Only[/bold]")
    console.print(f"Input: {input_label}")
    console.print(f"Filter: {filter_label}")
    console.print(f"URLs to process: {len(urls)}")
    console.print(f"Modes: {', '.join(modes)}")
    console.print(f"Output: {output_dir}\n")

    # Stream metrics to JSONL files — no in-memory accumulation
    mode_files: dict[str, object] = {}
    for mode in modes:
        mode_files[mode] = open(output_dir / f"raw_metrics_{mode}.jsonl", "w")

    try:
        async with async_playwright() as pw:
            for mode in modes:
                mode_cfg = config.MODE_CONFIG[mode]
                try:
                    browser = await pw.chromium.launch(
                        headless=True,
                        channel=mode_cfg["channel"],
                        args=["--no-sandbox"],
                    )
                    version = browser.version
                    await browser.close()
                    console.print(f"[green]{mode} ({mode_cfg['channel']}): Chrome {version}[/green]")
                except Exception as e:
                    console.print(f"[red]{mode} browser not available: {e}[/red]")
                    return
            console.print()

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Collecting...", total=len(urls))

                for i in range(0, len(urls), args.batch_size):
                    batch = urls[i : i + args.batch_size]

                    for ranked_url in batch:
                        progress.update(
                            task,
                            description=f"[{ranked_url.rank}] {ranked_url.host}",
                        )

                        try:
                            url_metrics = await process_url(
                                pw, ranked_url, output_dir, modes
                            )
                            for mode, m in url_metrics.items():
                                entry = {
                                    "host": ranked_url.host,
                                    "rank": ranked_url.rank,
                                    mode: asdict(m),
                                }
                                mode_files[mode].write(
                                    json.dumps(entry, default=str) + "\n"
                                )
                                mode_files[mode].flush()
                            del url_metrics

                        except Exception as e:
                            console.print(
                                f"\n[red]Error processing {ranked_url.host}: {e}[/red]"
                            )
                            traceback.print_exc()
                            del e

                        progress.advance(task)

                    gc.collect()

    except BaseException as e:
        console.print(f"\n[bold red]Fatal error: {e}[/bold red]")
        traceback.print_exc()
        del e
    finally:
        for f in mode_files.values():
            f.close()
        # Convert JSONL to JSON for backward compatibility
        for mode in modes:
            _jsonl_to_json(output_dir, mode)

    console.print("\n[bold green]Collection complete.[/bold green]")
    for mode in modes:
        path = output_dir / f"raw_metrics_{mode}.json"
        console.print(f"  {path}")
    console.print()


async def _full_run(args):
    """Original full pipeline: collect all modes + compare + report."""
    modes = args.modes.split(",")
    invalid = [m for m in modes if m not in config.MODE_CONFIG]
    if invalid:
        console.print(f"[red]Unknown modes: {', '.join(invalid)}. "
                       f"Choose from: {', '.join(config.MODE_CONFIG)}[/red]")
        return
    if "headful" not in modes:
        console.print("[red]headful mode is required as the baseline[/red]")
        return
    target_modes = [m for m in modes if m != "headful"]
    diff_pairs = _parse_diff_pairs(getattr(args, "diff_pairs", None))

    output_dir: Path = args.output
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "screenshots").mkdir(exist_ok=True)
    (output_dir / "har").mkdir(exist_ok=True)

    urls, input_label, filter_label = _parse_urls(args)

    console.print("\n[bold]Rendering Comparison[/bold]")
    console.print(f"Input: {input_label}")
    console.print(f"Filter: {filter_label}")
    console.print(f"URLs to process: {len(urls)}")
    console.print(f"Modes: {', '.join(modes)}")
    console.print(f"Output: {output_dir}\n")

    all_comparisons: list[ComparisonResult] = []
    raw_metrics_file = open(output_dir / "raw_metrics.jsonl", "w")

    def _save_progress() -> None:
        if all_comparisons:
            generate_markdown_report(all_comparisons, output_dir)
            generate_csv(all_comparisons, output_dir)

    try:
        async with async_playwright() as pw:
            for mode in modes:
                mode_cfg = config.MODE_CONFIG[mode]
                try:
                    browser = await pw.chromium.launch(
                        headless=True,
                        channel=mode_cfg["channel"],
                        args=["--no-sandbox"],
                    )
                    version = browser.version
                    await browser.close()
                    console.print(f"[green]{mode} ({mode_cfg['channel']}): Chrome {version}[/green]")
                except Exception as e:
                    console.print(f"[red]{mode} browser not available: {e}[/red]")
                    return
            console.print()

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Comparing URLs...", total=len(urls))

                for i in range(0, len(urls), args.batch_size):
                    batch = urls[i : i + args.batch_size]

                    for ranked_url in batch:
                        progress.update(
                            task,
                            description=f"[{ranked_url.rank}] {ranked_url.host}",
                        )

                        try:
                            url_metrics = await process_url(
                                pw, ranked_url, output_dir, modes
                            )

                            metric_entry: dict = {
                                "host": ranked_url.host,
                                "rank": ranked_url.rank,
                            }
                            for mode, m in url_metrics.items():
                                metric_entry[mode] = asdict(m)
                            raw_metrics_file.write(
                                json.dumps(metric_entry, default=str) + "\n"
                            )
                            raw_metrics_file.flush()

                            headful_metrics = url_metrics["headful"]
                            for target_mode in target_modes:
                                should_diff = (target_mode, "headful") in diff_pairs
                                comparison = compare(
                                    url_metrics[target_mode],
                                    headful_metrics,
                                    host=ranked_url.host,
                                    rank=ranked_url.rank,
                                    screenshots_dir=output_dir / "screenshots",
                                    generate_diff=should_diff,
                                )
                                comparison.compared_mode = target_mode
                                all_comparisons.append(comparison)

                            del url_metrics, metric_entry

                        except Exception as e:
                            console.print(
                                f"\n[red]Error processing {ranked_url.host}: {e}[/red]"
                            )
                            traceback.print_exc()
                            del e

                        progress.advance(task)

                    _save_progress()
                    gc.collect()

    except BaseException as e:
        console.print(f"\n[bold red]Fatal error: {e}[/bold red]")
        traceback.print_exc()
        del e
    finally:
        raw_metrics_file.close()
        _save_progress()
        # Convert JSONL to JSON for backward compatibility
        jsonl_path = output_dir / "raw_metrics.jsonl"
        if jsonl_path.exists():
            entries = []
            for line in jsonl_path.read_text().splitlines():
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
            save_raw_metrics(entries, output_dir)

    console.print("\n[bold green]Done.[/bold green]\n")


async def main():
    args = config.build_parser().parse_args()

    if args.merge_report:
        _merge_report(args)
        return

    if args.collect_only:
        await _collect_only(args)
        return

    await _full_run(args)


if __name__ == "__main__":
    asyncio.run(main())
