#!/usr/bin/env python3
"""Unified CLI for analysis tools.

Usage:
    uv run python -m analysis stats <job_dir>
    uv run python -m analysis scaling-stats <job_dir>
    uv run python -m analysis scaling-quality <job_dir> [--baseline-job <dir>]
    uv run python -m analysis scaling-comparison <job_dir> [--baseline-job <dir>]
    uv run python -m analysis container-metrics <job_dir>
"""

import sys
from pathlib import Path


SUBCOMMANDS = {
    "stats": ("analysis.comparison_stats", "Comprehensive 3-mode statistics report"),
    "scaling-stats": ("analysis.scaling_stats", "Scaling performance report (throughput, memory, CPU)"),
    "scaling-quality": ("analysis.scaling_quality", "Scaling quality degradation analysis"),
    "scaling-comparison": ("analysis.scaling_comparison", "Per-URL quality comparison across worker counts"),
    "container-metrics": ("analysis.container_metrics", "Container cgroup memory analysis"),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        prog = "hpb-analyze" if "hpb-analyze" in sys.argv[0] else "python -m analysis"
        print(f"Usage: {prog} <subcommand> [args...]\n")
        print("Subcommands:")
        for name, (_, desc) in SUBCOMMANDS.items():
            print(f"  {name:<25} {desc}")
        print(f"\nRun '{prog} <subcommand> --help' for subcommand help.")
        sys.exit(0)

    subcmd = sys.argv[1]
    if subcmd not in SUBCOMMANDS:
        print(f"Unknown subcommand: {subcmd}")
        print(f"Available: {', '.join(SUBCOMMANDS)}")
        sys.exit(1)

    module_path, _ = SUBCOMMANDS[subcmd]

    # Validate job_dir argument if provided (first non-flag arg after subcommand)
    remaining = sys.argv[2:]
    positional = [a for a in remaining if not a.startswith("-")]
    if positional:
        job_dir = Path(positional[0])
        if not job_dir.exists():
            print(f"Error: job directory not found: {job_dir}")
            sys.exit(1)
        if not job_dir.is_dir():
            print(f"Error: not a directory: {job_dir}")
            sys.exit(1)

    # Remove the subcommand from argv so the module's argparse sees the right args
    sys.argv = [f"python -m analysis {subcmd}"] + sys.argv[2:]

    import importlib
    mod = importlib.import_module(module_path)
    mod.main()


if __name__ == "__main__":
    main()
