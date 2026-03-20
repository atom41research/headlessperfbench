#!/usr/bin/env python3
"""Orchestrate rendering comparison across 3 Docker containers.

Usage:
    uv run python run.py --urls-file urls_10.txt
    uv run python run.py --urls-file urls_10.txt --limit 10
    uv run python run.py --no-build --urls-file urls_10.txt
    uv run python run.py --report-only --job-dir output/jobs/job_xxx
    uv run python run.py --urls-file urls_10.txt --cpus 2 --memory 4G
"""

import argparse
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from analysis.utils import load_urls, run_cmd

PROJECT_DIR = Path(__file__).resolve().parent
COMPOSE_FILE = PROJECT_DIR / "docker-compose.yml"
JOBS_DIR = PROJECT_DIR / "output" / "jobs"

SERVICES = ["headless", "headful", "headless-shell"]


def build_images() -> None:
    """Build all 3 Docker images in parallel, no cache."""
    print("==> Building Docker images (no cache, parallel)")
    cmd = [
        "docker", "compose", "-f", str(COMPOSE_FILE),
        "build", "--no-cache", "--parallel",
    ] + SERVICES
    run_cmd(cmd)


def run_container(
    service: str,
    urls_volume: str,
    output_volume: str,
    extra_args: list[str],
    cpus: str = "",
    memory: str = "",
) -> bool:
    """Run a single container for collect-only mode."""
    print(f"==> Running {service} container"
          f"{f' (cpus={cpus}, memory={memory})' if cpus or memory else ''}")
    cmd = [
        "docker", "compose", "-f", str(COMPOSE_FILE),
        "run", "--rm",
    ]
    if cpus:
        cmd += ["--cpus", cpus]
    if memory:
        cmd += ["--memory", memory]
    cmd += [
        "-v", urls_volume,
        "-v", output_volume,
        service,
        "--collect-only",
        "--modes", service,
        "--url-list", "urls.txt",
        "--output", "output",
        *extra_args,
    ]
    result = run_cmd(cmd, check=False)
    if result.returncode != 0:
        print(f"Error: {service} container failed (exit {result.returncode})")
        return False
    print(f"==> {service} complete")
    return True


def merge_report(job_dir: Path, diff_pairs: str | None = None) -> None:
    """Run merge-report to combine per-mode results and generate reports."""
    print("==> Merging results and generating reports")
    cmd = [
        "uv", "run", "python", "-m", "collector",
        "--merge-report",
        "--modes", ",".join(SERVICES),
        "--output", str(job_dir),
    ]
    if diff_pairs:
        cmd += ["--diff-pairs", diff_pairs]
    run_cmd(cmd)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and run rendering comparison in Docker containers.",
    )
    parser.add_argument("--urls-file", type=Path, required=False,
                        help="File with one URL per line")
    parser.add_argument("--limit", type=int, default=0,
                        help="Only use the first N URLs (default: all)")
    parser.add_argument("--top-n", type=int, default=None,
                        help="Pass --top-n to collector")
    parser.add_argument("--start-rank", type=int, default=1,
                        help="Pass --start-rank to collector")
    parser.add_argument("--batch-size", type=int, default=10,
                        help="Pass --batch-size to collector")
    parser.add_argument("--no-build", action="store_true",
                        help="Skip Docker image build")
    parser.add_argument("--report-only", action="store_true",
                        help="Only run merge-report on an existing job")
    parser.add_argument("--job-dir", type=Path, default=None,
                        help="Existing job directory (for --report-only or to append)")
    parser.add_argument("--parallel", action="store_true",
                        help="Run containers in parallel (default: sequential)")
    parser.add_argument("--cpus", type=str, default="",
                        help="Docker CPU limit per container (e.g. '2', '4'). "
                             "Overrides docker-compose.yml setting.")
    parser.add_argument("--memory", type=str, default="",
                        help="Docker memory limit per container (e.g. '4G', '8G'). "
                             "Overrides docker-compose.yml setting.")
    parser.add_argument("--diff-pairs", type=str, default=None,
                        help="Comma-separated pairs for diff images, e.g. 'HL-HF,HS-HF'. "
                             "If omitted, no diff images are generated.")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.report_only:
        job_dir = args.job_dir
        if not job_dir or not job_dir.exists():
            print("Error: --job-dir required for --report-only", file=sys.stderr)
            sys.exit(1)
        merge_report(job_dir, diff_pairs=args.diff_pairs)
        return

    if not args.urls_file:
        print("Error: --urls-file is required (unless --report-only)", file=sys.stderr)
        sys.exit(1)

    urls_path = args.urls_file.resolve()
    if not urls_path.is_file():
        print(f"Error: URLs file not found: {urls_path}", file=sys.stderr)
        sys.exit(1)

    urls = load_urls(urls_path, args.limit)
    if not urls:
        print("Error: no URLs found in file", file=sys.stderr)
        sys.exit(1)
    print(f"==> {len(urls)} URLs loaded"
          f"{f' (limited to {args.limit})' if args.limit else ''}")

    # Job directory
    if args.job_dir:
        job_dir = args.job_dir
        job_dir.mkdir(parents=True, exist_ok=True)
        print(f"==> Using job directory: {job_dir}")
    else:
        job_name = "job_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        job_dir = JOBS_DIR / job_name
        job_dir.mkdir(parents=True, exist_ok=True)
        print(f"==> Job directory: {job_dir}")

    (job_dir / "screenshots").mkdir(exist_ok=True)
    (job_dir / "har").mkdir(exist_ok=True)

    # Write cleaned URL list to a temp file for mounting
    tmp_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", prefix="rc_urls_", delete=False
    )
    tmp_file.write("\n".join(urls) + "\n")
    tmp_file.flush()

    urls_volume = f"{tmp_file.name}:/app/urls.txt:ro"
    output_volume = f"{job_dir.resolve()}:/app/output"

    # Extra args to pass through
    extra_args: list[str] = []
    if args.top_n is not None:
        extra_args += ["--top-n", str(args.top_n)]
    if args.start_rank != 1:
        extra_args += ["--start-rank", str(args.start_rank)]
    if args.batch_size != 10:
        extra_args += ["--batch-size", str(args.batch_size)]

    try:
        if not args.no_build:
            build_images()

        run_parallel = args.parallel

        if run_parallel:
            print(f"==> Running {len(SERVICES)} containers in parallel")
            with ThreadPoolExecutor(max_workers=len(SERVICES)) as pool:
                futures = {
                    pool.submit(
                        run_container, service, urls_volume, output_volume,
                        extra_args, args.cpus, args.memory,
                    ): service
                    for service in SERVICES
                }
                failed = []
                for future in as_completed(futures):
                    service = futures[future]
                    try:
                        if not future.result():
                            failed.append(service)
                    except Exception as e:
                        print(f"Error: {service} raised {e}")
                        failed.append(service)
                if failed:
                    print(f"Warning: {', '.join(failed)} failed.")
        else:
            for service in SERVICES:
                run_container(service, urls_volume, output_volume,
                              extra_args, args.cpus, args.memory)

        # Merge results and generate reports
        merge_report(job_dir, diff_pairs=args.diff_pairs)

    finally:
        Path(tmp_file.name).unlink(missing_ok=True)

    print(f"\n==> Job complete: {job_dir}")


if __name__ == "__main__":
    main()
