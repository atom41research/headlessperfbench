# headlessperfbench

Performance and rendering fidelity benchmarks for Chrome headful, headless, and headless-shell modes.

This framework systematically measures behavioral differences between Chrome's three rendering modes under controlled Docker environments with cgroup v2 resource limits. It is the companion benchmarking code for a Black Hat 2026 presentation on headless browser detection techniques.

<!-- TODO: Add full citation once proceedings are published -->

---

## Key Findings

We tested 965 URLs from the Tranco top-1000 list across all three modes. Each non-headful mode was compared pairwise against headful (the baseline).

| Metric                  | Headless    | Headless-Shell |
|-------------------------|-------------|----------------|
| Identical to headful    | 30.6% (295) | 24.1% (233)    |
| Mean severity score     | 9.83        | 21.61          |
| Severity > 100          | 0.8% (8)    | 4.4% (42)      |
| Screenshot diff > 50%   | 2.3% (22)   | 5.0% (48)      |
| Errored (headless side) | 2.8% (27)   | 4.8% (46)      |

**Only 22.8% of sites render identically in both headless modes.** Standard headless is significantly more compatible than headless-shell, but headless-shell uses approximately 50% less memory (582 MB vs 1,130 MB peak RSS).

**Headless-shell fails on modern JS-framework sites.** Sites built with React, Next.js, and similar frameworks (salesforce.com, autodesk.com, reddit.com, wordpress.com) serve blank or skeleton pages to headless-shell -- severity 240--268 versus less than 10 in standard headless.

**Headful and standard headless are near-identical** in resource usage (1.06x RSS, 1.01x CPU), DOM content (1.00x), and network behavior (1.00x).

**77.2% of sites have some detectable rendering difference** in at least one headless mode, even with anti-detection measures applied.

Full results are documented in [`docs/results_analysis.md`](docs/results_analysis.md).

---

## Quick Start

### Docker (recommended)

Docker provides reproducible measurements with cgroup v2 resource isolation (4 CPUs, 8 GB RAM per container).

```bash
git clone https://github.com/atom41research/headlessperfbench.git
cd headlessperfbench

# Run 3-mode comparison on 10 sample URLs
uv run python run.py --urls-file examples/urls_10.txt

# Skip rebuild on subsequent runs
uv run python run.py --no-build --urls-file examples/urls_10.txt
```

### Local (no Docker)

```bash
git clone https://github.com/atom41research/headlessperfbench.git
cd headlessperfbench
uv sync
uv run playwright install chrome

# Direct collection — headless only (simplest, no extra setup)
uv run python -m collector --url-list examples/urls_10.txt --modes headless

# Full 3-mode comparison (headful needs Xvfb, headless-shell needs `uv run playwright install`)
uv run python -m collector --url-list examples/urls_10.txt --modes headful,headless,headless-shell
```

---

## Usage

### 3-Mode Comparison

`run.py` orchestrates side-by-side data collection across all three browser modes, each in its own Docker container.

```bash
# Full run: build images, collect data in all 3 modes, merge and report
uv run python run.py --urls-file examples/urls_10.txt

# Limit to first N URLs
uv run python run.py --urls-file urls.txt --limit 10

# Run all 3 containers in parallel (requires sufficient resources)
uv run python run.py --parallel --urls-file urls.txt

# Generate diff images for specific mode pairs
uv run python run.py --urls-file urls.txt --diff-pairs HL-HF,HS-HF

# Re-generate reports from a previous job without re-collecting
uv run python run.py --report-only --job-dir output/jobs/job_20260312_001013
```

Diff pair abbreviations: `HL` = headless, `HF` = headful, `HS` = headless-shell.

Output goes to `output/jobs/job_YYYYMMDD_HHMMSS/` containing screenshots, HAR files, per-mode raw metrics, merged metrics, a markdown report, and a CSV.

### Scaling Benchmarks

`run_scaling.py` measures how concurrent browser instances affect throughput, resource usage, and result consistency within a single container.

```bash
# Default matrix: headful x {1,2,3,4} workers, headless-shell x {4,8,12,16} workers
uv run python run_scaling.py --urls-file examples/urls_10.txt

# Custom modes and worker counts
uv run python run_scaling.py --urls-file urls.txt --modes headless-shell --workers 4,8,16

# Report from existing data
uv run python run_scaling.py --report-only --job-dir output/jobs/scaling_20260312_001013
```

---

## Analysis Tools

The `analysis/` package provides a unified CLI for post-collection analysis:

```bash
uv run python -m analysis <subcommand> <job_dir> [options]
```

| Subcommand | Description |
|---|---|
| `stats` | Comprehensive 3-mode statistics report (comparison job) |
| `scaling-stats` | Scaling performance report: throughput, memory, CPU |
| `scaling-quality` | Scaling quality degradation analysis |
| `scaling-comparison` | Per-URL quality comparison across worker counts |
| `container-metrics` | Container cgroup memory analysis |

Examples:

```bash
uv run python -m analysis stats output/jobs/job_20260312_001013
uv run python -m analysis scaling-stats output/jobs/scaling_20260312_001013
uv run python -m analysis scaling-quality output/jobs/scaling_20260312_001013 --baseline-job output/jobs/job_20260312_001013
```

---

## Architecture

### Browser Modes

| Mode | Binary | Display | Launch Method |
|---|---|---|---|
| `headful` | System Chrome (`channel="chrome"`) | Xvfb (virtual) | Real GUI rendering via virtual display |
| `headless` | System Chrome (`channel="chrome"`) | None | `--headless=new` flag |
| `headless-shell` | Playwright's `chromium-headless-shell` | None | Stripped headless-only binary |

All three modes share the same data collection code in `collector/`. Only the binary and headless flag differ.

### Docker Setup

A single multi-stage `Dockerfile` with build targets for each mode:

- **base** -- Python 3.12 + system deps + uv + Python deps
- **chrome** -- base + Google Chrome stable + Playwright Chrome channel
- **headless** -- FROM chrome (no extras needed)
- **headful** -- FROM chrome + Xvfb + GTK libs + virtual display entrypoint
- **headless-shell** -- FROM base + Playwright's `chromium-headless-shell`

`docker-compose.yml` uses `target:` to select the build stage. Each container is allocated 4 CPUs, 8 GB RAM, and 8 GB shared memory (`/dev/shm`).

### Anti-Detection Measures

To ensure headless and headful modes behave as similarly as possible (isolating only the rendering pipeline differences), all modes apply:

- **User-agent spoofing** -- headless modes use a user-agent string matching headful Chrome, preventing server-side UA-based detection.
- **Automation flag removal** -- `--disable-blink-features=AutomationControlled` suppresses `navigator.webdriver` and related automation markers.
- **System Chrome** -- headful and headless modes use the system-installed Google Chrome (not Playwright's bundled Chromium), ensuring identical binary and feature sets.

### Orchestrators

`run.py` manages the full 3-mode Docker workflow:

1. **Build** -- Builds all 3 Docker images in parallel (no cache)
2. **Collect** -- Runs each container in `--collect-only` mode, one per browser mode
3. **Merge** -- Combines per-mode results on the host, compares against the headful baseline, generates reports
4. **Diff images** -- Optional, generated only when `--diff-pairs` is specified

`run_scaling.py` follows a similar pattern but iterates over a matrix of (mode, worker count) configurations, running each sequentially for isolated measurements.

---

## Project Structure

```
headlessperfbench/
  run.py                        # 3-mode comparison orchestrator
  run_scaling.py                # Scaling benchmark orchestrator
  Dockerfile                    # Multi-stage: headless, headful, headless-shell
  docker-compose.yml            # Per-mode service definitions
  entrypoint.headful.sh         # Xvfb startup for headful container
  pyproject.toml                # Project config and dependencies
  collector/                    # Core data collection (Playwright-based)
    collector.py                #   Page visit, metric extraction, screenshots, HAR
    comparator.py               #   Cross-mode comparison and diff images
    config.py                   #   Browser launch configuration per mode
    report.py                   #   Markdown and CSV report generation
    scaling.py                  #   Concurrent worker management
    parser.py                   #   CLI argument parsing
    __main__.py                 #   Package entry point
  analysis/                     # Post-collection analysis CLI
    __main__.py                 #   Subcommand dispatcher
    comparison_stats.py         #   3-mode statistical analysis
    scaling_stats.py            #   Scaling performance metrics
    scaling_quality.py          #   Quality degradation under load
    scaling_comparison.py       #   Per-URL cross-worker comparison
    container_metrics.py        #   cgroup memory analysis
    utils.py                    #   Shared utilities
  tools/
    minimize_hars.py            # Strip response bodies from HAR files
  docs/
    methodology.md              # Experimental design and measurement approach
    results_analysis.md         # Full 1000-URL comparative analysis
  examples/
    quickstart.md               # Step-by-step usage guide
    urls_10.txt                 # Sample URL list (top 10 sites)
  output/jobs/                  # Collected data (git-ignored)
```

---

## Metrics Collected

For each URL visited in each browser mode, the framework records:

| Category | Metrics |
|---|---|
| HTTP | Status code |
| DOM | Element count, serialized DOM size (bytes), visible text length, per-tag counts, structural element presence |
| Network | Total request count, request types, Resource Timing API (resource count, transfer bytes, decoded bytes) |
| Timing | DNS, TTFB, DOM interactive, DOM content loaded, DOM complete, load event (ms) |
| Resources | Peak RSS/USS memory, CPU time, Chrome process tree sampling, container cgroup metrics |
| Visual | Full-page screenshot (PNG), HAR file (HTTP archive) |

---

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Google Chrome (system install) -- for headful and headless modes
- Docker and Docker Compose -- for containerized runs (recommended)
- Display server (X11/Wayland) for non-Docker headful mode, or Xvfb

---

## Citation

Presented at Black Hat 2026.

```
@inproceedings{headlessperfbench-bh2026,
  title     = {TODO},
  author    = {TODO},
  booktitle = {Black Hat USA 2026},
  year      = {2026}
}
```

---

## License

This project is licensed under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE) for details.
