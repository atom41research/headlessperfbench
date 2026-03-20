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


SUBCOMMANDS = {
    "stats": ("analysis.comparison_stats", "Comprehensive 3-mode statistics report"),
    "scaling-stats": ("analysis.scaling_stats", "Scaling performance report (throughput, memory, CPU)"),
    "scaling-quality": ("analysis.scaling_quality", "Scaling quality degradation analysis"),
    "scaling-comparison": ("analysis.scaling_comparison", "Per-URL quality comparison across worker counts"),
    "container-metrics": ("analysis.container_metrics", "Container cgroup memory analysis"),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python -m analysis <subcommand> [args...]\n")
        print("Subcommands:")
        for name, (_, desc) in SUBCOMMANDS.items():
            print(f"  {name:<25} {desc}")
        print("\nRun 'python -m analysis <subcommand> --help' for subcommand help.")
        sys.exit(0)

    subcmd = sys.argv[1]
    if subcmd not in SUBCOMMANDS:
        print(f"Unknown subcommand: {subcmd}")
        print(f"Available: {', '.join(SUBCOMMANDS)}")
        sys.exit(1)

    module_path, _ = SUBCOMMANDS[subcmd]

    # Remove the subcommand from argv so the module's argparse sees the right args
    sys.argv = [f"python -m analysis {subcmd}"] + sys.argv[2:]

    import importlib
    mod = importlib.import_module(module_path)
    mod.main()


if __name__ == "__main__":
    main()
