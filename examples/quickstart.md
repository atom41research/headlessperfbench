# Quickstart Guide

A step-by-step guide to running headless vs headful Chrome rendering comparisons and scaling benchmarks.

---

## 1. Prerequisites

- **Docker** and **Docker Compose** (v2)
- **uv** (Python package manager, [installation](https://docs.astral.sh/uv/getting-started/installation/))
- **Python 3.12+**
- **Google Chrome** (for local runs outside Docker)

## 2. Installation

```bash
git clone https://github.com/atom41research/headlessperfbench.git
cd headlessperfbench
uv sync
uv run playwright install chrome
```

`uv sync` installs all project dependencies from the lockfile. `uv run playwright install chrome` downloads the Chrome browser driver needed by Playwright.

## 3. Running a 3-Mode Comparison

```bash
uv run python run.py --urls-file examples/urls_10.txt
```

This command performs the following steps:

1. **Builds 3 Docker images** (one per mode: headful, headless, headless-shell) using the multi-stage `Dockerfile`. Each image has its own browser configuration and dependencies.
2. **Runs each mode sequentially** in isolated Docker containers with cgroup v2 resource limits (4 CPUs, 8 GB RAM, 8 GB shared memory). Sequential execution ensures modes do not compete for host resources.
3. **Merges results** from the per-mode `raw_metrics_{mode}.json` files into a combined `raw_metrics.json`.
4. **Generates reports** including a markdown comparison report (`report.md`) and a CSV summary (`results.csv`).

## 4. Running Scaling Benchmarks

```bash
uv run python run_scaling.py --urls-file examples/urls_10.txt --modes headless-shell --workers 1,2,3,4
```

This measures how concurrent browser instances within a single container affect throughput, resource usage, and data quality. For each `(mode, worker_count)` combination:

- A Docker container runs N worker processes, each with its own browser instance.
- URLs are distributed across workers via a shared queue.
- Wall time, per-worker throughput, container memory, and CPU utilization are recorded.
- Configurations run sequentially for isolated measurement.

If `--modes` and `--workers` are omitted, the default matrix is used: headful at 1/2/3/4 workers, headless-shell at 4/8/12/16 workers.

## 5. Analyzing Results

All analysis subcommands are available under `python -m analysis`:

### Comprehensive 3-mode statistics

```bash
uv run python -m analysis stats output/jobs/job_xxx
```

Produces `comprehensive_stats.md` with summary and detail tables for performance metrics (CPU time, RSS, USS, container memory, CPU utilization), quality metrics (DOM element count, DOM size, visible text, network requests, HTTP status), rendering fidelity (screenshot diff percentage, DOM/content ratios, severity scores), and error summaries per mode.

### Scaling performance report

```bash
uv run python -m analysis scaling-stats output/jobs/scaling_xxx
```

Produces `scaling_report.md` with throughput tables (wall time, URLs/sec, speedup, efficiency), container memory and CPU tables per worker count, worker utilization breakdown, result consistency analysis (coefficient of variation across worker counts), and exported timeline CSVs for plotting.

### Scaling quality degradation analysis

```bash
uv run python -m analysis scaling-quality output/jobs/scaling_xxx
```

Produces `scaling_analysis.md` with summary tables showing quality delta versus baseline (1 worker), per-URL quality matrix (OK / WARN / DEGRADED / FAILED), detailed degradation list for URLs with significant changes, and composite quality scores (DOM, content, network, timing) per worker count.

### Per-URL scaling comparison

```bash
uv run python -m analysis scaling-comparison output/jobs/scaling_xxx
```

Produces `quality_comparison.md` with side-by-side per-URL metric tables across all worker counts, navigation timing comparisons, per-instance resource usage, degradation flags with percentage-change annotations, and composite quality scores.

### Container cgroup memory analysis

```bash
uv run python -m analysis container-metrics output/jobs/scaling_xxx
```

Prints a bucketed memory progression analysis showing container total memory (includes page cache), container active memory (anon + kernel, the meaningful metric), page cache component, and cross-validation between Chrome RSS/USS and container-level measurements. Useful for understanding why `memory.current` grows monotonically due to Linux page cache accumulation.

## 6. Output Directory Structure

### 3-mode comparison jobs

```
output/jobs/job_YYYYMMDD_HHMMSS/
├── raw_metrics_headful.json
├── raw_metrics_headful.jsonl
├── raw_metrics_headless.json
├── raw_metrics_headless.jsonl
├── raw_metrics_headless-shell.json
├── raw_metrics_headless-shell.jsonl
├── raw_metrics.json
├── report.md
├── results.csv
├── screenshots/
└── har/
```

- `raw_metrics_{mode}.json` -- per-URL metrics collected by that mode's container.
- `raw_metrics_{mode}.jsonl` -- streaming JSONL format (written during collection).
- `raw_metrics.json` -- combined metrics from all three modes, merged by URL.
- `screenshots/` -- full-page PNG screenshots, named `{rank}_{host}_{mode}.png`.
- `har/` -- HTTP Archive files capturing all network requests.
- `report.md` -- markdown comparison report with diff severity analysis.
- `results.csv` -- tabular summary of per-URL comparisons.

### Scaling jobs

```
output/jobs/scaling_YYYYMMDD_HHMMSS/
├── headless-shell_1w/
│   ├── raw_metrics_headless-shell.json
│   ├── scaling_meta.json
│   ├── screenshots/
│   └── har/
├── headless-shell_2w/
│   ├── raw_metrics_headless-shell.json
│   ├── scaling_meta.json
│   ├── screenshots/
│   └── har/
├── headless-shell_4w/
│   ├── raw_metrics_headless-shell.json
│   ├── scaling_meta.json
│   ├── screenshots/
│   └── har/
└── scaling_report.md
```

- `scaling_meta.json` -- scaling-specific metadata: wall time, worker count, URL success/failure counts, cgroup timeline samples, and per-worker statistics.
- Each subdirectory (`{mode}_{N}w/`) contains the raw metrics, screenshots, and HAR files for that configuration.

## 7. Tips

- **`--no-build`** -- Skip Docker image rebuild when images are already up to date. Saves several minutes on repeated runs.

- **`--limit N`** -- Process only the first N URLs from the input file. Useful for quick smoke tests.

- **`--parallel`** -- Run all three mode containers in parallel instead of sequentially. Requires sufficient host resources (12+ CPUs, 24+ GB RAM) to avoid contention.

- **`--diff-pairs HL-HF,HS-HF`** -- Generate visual diff images between mode pairs. Abbreviations: HL = headless, HF = headful, HS = headless-shell. Omit this flag to skip diff image generation entirely.

- **`--report-only --job-dir output/jobs/job_xxx`** -- Re-generate reports from an existing job without re-running containers. Useful after modifying analysis code.

- **`--batch-size N`** -- Control how many URLs are processed per batch within a container (default: 10).

- **`--job-dir output/jobs/job_xxx`** -- Append results to an existing job directory instead of creating a new one.
