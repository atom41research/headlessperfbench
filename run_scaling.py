#!/usr/bin/env python3
"""Orchestrate scaling tests across Docker containers.

Runs the rendering comparison with varying worker counts to measure how
concurrent browser instances affect throughput, resource usage, and result
consistency within a single container (4 CPU, 8 GB RAM).

Usage:
    uv run python run_scaling.py --urls-file urls_10.txt
    uv run python run_scaling.py --urls-file urls_10.txt --no-build
    uv run python run_scaling.py --urls-file urls_10.txt --modes headless-shell --workers 4,8
    uv run python run_scaling.py --report-only --job-dir output/jobs/scaling_xxx
    uv run python run_scaling.py --urls-file urls_10.txt --cpus 2 --memory 4G
"""

import argparse
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from analysis.utils import load_urls, run_cmd

PROJECT_DIR = Path(__file__).resolve().parent
COMPOSE_FILE = PROJECT_DIR / "docker-compose.yml"
JOBS_DIR = PROJECT_DIR / "output" / "jobs"

# Default test matrix: mode -> list of worker counts
SCALING_MATRIX: dict[str, list[int]] = {
    "headful": [1, 2, 3, 4],
    "headless-shell": [4, 8, 12, 16],
}


def build_images(services: list[str]) -> None:
    """Build Docker images for the requested services."""
    unique = list(dict.fromkeys(services))
    print(f"==> Building Docker images: {', '.join(unique)}")
    cmd = [
        "docker", "compose", "-f", str(COMPOSE_FILE),
        "build", "--no-cache", "--parallel",
    ] + unique
    run_cmd(cmd)


def run_scaling_container(
    service: str,
    num_workers: int,
    urls_volume: str,
    output_volume: str,
    extra_args: list[str],
    cpus: str = "",
    memory: str = "",
) -> bool:
    """Run one container for a (mode, workers) configuration."""
    print(f"\n==> Running {service} — {num_workers} workers"
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
        "--workers", str(num_workers),
        *extra_args,
    ]
    result = run_cmd(cmd, check=False)
    if result.returncode != 0:
        print(f"Error: {service} {num_workers}w failed (exit {result.returncode})")
        return False
    print(f"==> {service} {num_workers}w complete")
    return True


def generate_report(job_dir: Path) -> None:
    """Run the scaling stats generator."""
    print("\n==> Generating scaling report")
    cmd = ["uv", "run", "python", "-m", "analysis", "scaling-stats", str(job_dir)]
    run_cmd(cmd, check=False)


def parse_matrix(
    modes_str: str | None,
    workers_str: str | None,
) -> list[tuple[str, int]]:
    """Build list of (mode, num_workers) from CLI or defaults."""
    if modes_str and workers_str:
        modes = [m.strip() for m in modes_str.split(",")]
        counts = [int(w.strip()) for w in workers_str.split(",")]
        return [(m, w) for m in modes for w in counts]

    if modes_str:
        modes = [m.strip() for m in modes_str.split(",")]
        matrix = []
        for m in modes:
            if m in SCALING_MATRIX:
                matrix.extend((m, w) for w in SCALING_MATRIX[m])
            else:
                matrix.append((m, 1))
        return matrix

    # Default full matrix
    matrix = []
    for mode, counts in SCALING_MATRIX.items():
        matrix.extend((mode, w) for w in counts)
    return matrix


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run scaling tests with varying worker counts in Docker.",
    )
    parser.add_argument("--urls-file", type=Path, required=False,
                        help="File with one URL per line")
    parser.add_argument("--limit", type=int, default=0,
                        help="Only use the first N URLs (default: all)")
    parser.add_argument("--modes", type=str, default=None,
                        help="Comma-separated modes to test (default: headful,headless-shell)")
    parser.add_argument("--workers", type=str, default=None,
                        help="Comma-separated worker counts per mode (default: use built-in matrix)")
    parser.add_argument("--no-build", action="store_true",
                        help="Skip Docker image build")
    parser.add_argument("--report-only", action="store_true",
                        help="Only generate report from existing job")
    parser.add_argument("--job-dir", type=Path, default=None,
                        help="Existing job directory (for --report-only)")
    parser.add_argument("--batch-size", type=int, default=10,
                        help="Batch size passed to collector")
    parser.add_argument("--cpus", type=str, default="",
                        help="Docker CPU limit per container (e.g. '2', '4'). "
                             "Overrides docker-compose.yml setting.")
    parser.add_argument("--memory", type=str, default="",
                        help="Docker memory limit per container (e.g. '4G', '8G'). "
                             "Overrides docker-compose.yml setting.")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.report_only:
        if not args.job_dir or not args.job_dir.exists():
            print("Error: --job-dir required for --report-only", file=sys.stderr)
            sys.exit(1)
        generate_report(args.job_dir)
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

    matrix = parse_matrix(args.modes, args.workers)
    if not matrix:
        print("Error: empty test matrix", file=sys.stderr)
        sys.exit(1)

    print(f"==> {len(urls)} URLs loaded"
          f"{f' (limited to {args.limit})' if args.limit else ''}")
    print(f"==> Test matrix: {len(matrix)} configurations")
    for mode, w in matrix:
        print(f"     {mode} x {w}w")

    # Job directory
    if args.job_dir:
        job_dir = args.job_dir
        job_dir.mkdir(parents=True, exist_ok=True)
    else:
        job_name = "scaling_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        job_dir = JOBS_DIR / job_name
        job_dir.mkdir(parents=True, exist_ok=True)
    print(f"==> Job directory: {job_dir}")

    # Write cleaned URL list to a temp file for mounting
    tmp_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", prefix="sc_urls_", delete=False,
    )
    tmp_file.write("\n".join(urls) + "\n")
    tmp_file.flush()
    urls_volume = f"{tmp_file.name}:/app/urls.txt:ro"

    # Extra args
    extra_args: list[str] = []
    if args.batch_size != 10:
        extra_args += ["--batch-size", str(args.batch_size)]

    try:
        # Build images (only the services we need)
        if not args.no_build:
            services = list(dict.fromkeys(m for m, _ in matrix))
            build_images(services)

        # Run configurations sequentially for isolated measurements
        failed: list[str] = []
        for mode, num_workers in matrix:
            sub_name = f"{mode}_{num_workers}w"
            sub_dir = job_dir / sub_name
            sub_dir.mkdir(parents=True, exist_ok=True)

            output_volume = f"{sub_dir.resolve()}:/app/output"

            ok = run_scaling_container(
                mode, num_workers, urls_volume, output_volume, extra_args,
                args.cpus, args.memory,
            )
            if not ok:
                failed.append(sub_name)

        if failed:
            print(f"\nWarning: failed configurations: {', '.join(failed)}")

        # Generate comparison report
        generate_report(job_dir)

    finally:
        Path(tmp_file.name).unlink(missing_ok=True)

    print(f"\n==> Scaling job complete: {job_dir}")


if __name__ == "__main__":
    main()
