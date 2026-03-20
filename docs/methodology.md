# Experimental Methodology

This document describes the experimental design, data collection protocol, and measurement approach used by headlessperfbench.

---

## 1. Objective

Quantify behavioral differences between Chrome's three rendering modes -- headful, headless, and headless-shell -- under controlled conditions. Measure how concurrent browser instances within a single container affect data quality and throughput. The goal is to determine whether headless modes produce equivalent output to headful Chrome, and at what concurrency levels quality begins to degrade.

## 2. Environment

All experiments run inside Docker containers with cgroup v2 resource limits to ensure consistent, reproducible conditions.

**Container specification:**
- 4 CPUs per container
- 8 GB RAM per container
- 8 GB shared memory (`shm_size: 8g`)
- `SYS_ADMIN` capability and `seccomp=unconfined` for Chrome sandboxing support
- Base image: `python:3.12-slim-bookworm`

**Software stack:**
- Python 3.12
- Playwright for browser automation
- psutil for Chrome process tree monitoring
- cgroup v2 kernel interfaces for container-level memory and CPU measurement

**Isolation strategy:**
- In 3-mode comparison runs, containers execute sequentially -- one mode at a time -- so that modes do not compete for host resources.
- In scaling runs, each `(mode, worker_count)` configuration runs in its own sequential container invocation.

## 3. Browser Modes

Three rendering modes are tested, each representing a distinct Chrome execution environment.

### headful

System Google Chrome (`channel="chrome"`) launched with a full GUI rendering pipeline. An Xvfb virtual framebuffer provides the X11 display server required for headful operation inside a container. This mode exercises the complete compositor, GPU rasterization path (software-fallback in Docker), and window management code. It serves as the baseline for comparison since it is the closest to how a real user's browser operates.

### headless

System Google Chrome (`channel="chrome"`) launched with Chrome's built-in headless mode (`--headless=new`). This uses the same Chrome binary as headful but skips the X11 display server. Chrome renders pages internally using its headless compositor. No Xvfb is required.

### headless-shell

Playwright's `chromium-headless-shell` binary (`channel="chromium-headless-shell"`), a stripped Chromium build designed exclusively for headless operation. This binary omits GUI-related code paths entirely and is smaller than full Chrome. It does not require a system Chrome installation.

## 4. Anti-Detection Measures

All three modes apply the same anti-detection configuration to ensure websites serve identical content regardless of mode.

- **User-agent string:** All modes use a user-agent matching headful Chrome on Linux (`Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36`). Headless and headless-shell modes do not reveal `HeadlessChrome` in the UA string.

- **Automation flag suppression:** Chrome is launched with `--disable-blink-features=AutomationControlled`, which prevents the browser from setting `navigator.webdriver=true`. Additionally, a Playwright init script patches `navigator.webdriver` to return `undefined`.

- **System Chrome binary:** Headful and headless modes use the system-installed Google Chrome (`channel="chrome"`) rather than Playwright's bundled Chromium, ensuring the browser fingerprint (version, features, behavior) matches a standard Chrome installation.

## 5. Data Collection Protocol

### Page visit procedure

Each URL is visited sequentially within a mode (in single-worker mode). The procedure for each URL:

1. Launch a fresh browser instance via Playwright.
2. Start a background resource sampler that periodically (every 250ms) records Chrome process tree RSS, USS, CPU time, process count, and container cgroup metrics.
3. Create a new browser context with HAR recording enabled (`record_har_omit_content: true`).
4. Navigate to the URL with a `domcontentloaded` wait condition and a 10-second timeout. Timeout is non-fatal -- the page is partially loaded and metrics are still collected.
5. Wait 2 seconds for dynamic content to settle.
6. Execute JavaScript to collect page metrics.
7. Stop the resource sampler and record pre-screenshot measurements.
8. Capture a viewport-size screenshot (PNG, 1280x720).
9. Record post-screenshot resource measurements (includes compositing cost).
10. Close the browser context (flushes HAR file) and browser instance.

### Metrics captured per URL

**Content metrics:**
- HTTP status code
- DOM element count
- DOM serialized byte size (`outerHTML.length`)
- Visible text length (`body.innerText.length`)
- Tag counts (per HTML element type)
- Structural element presence (nav, main, footer, article, header, aside, section, form, table, dialog)

**Network metrics:**
- Total network request count (via Playwright request event listener)
- Request counts by resource type (document, script, stylesheet, image, etc.)
- Resource Timing API: resource count, total transfer bytes, decoded bytes, resources by initiator type

**Navigation timing (via Performance API):**
- DNS lookup duration
- TCP connect duration
- Time to first byte (TTFB)
- Response duration
- DOM interactive time
- DOMContentLoaded event end time
- DOM complete time
- Load event end time

**Resource usage (Chrome process tree via psutil):**
- Peak RSS and USS (before and after screenshot)
- CPU time (user + system, before and after screenshot)
- Average and peak Chrome RSS and USS (from periodic sampling)
- Average and peak Chrome CPU utilization percentage
- Peak process count in the Chrome tree

**Container-level metrics (cgroup v2, when running in Docker):**
- `memory.current` (total container memory, includes page cache)
- Active memory (anon + kernel from `memory.stat`, excludes page cache)
- Container CPU utilization percentage (from `cpu.stat usage_usec`)

**Artifacts:**
- Full-page screenshot (PNG)
- HAR file (HTTP Archive, content omitted to save space)

## 6. Scaling Methodology

Scaling tests measure how concurrent browser instances within a single container affect throughput and data quality.

### Worker architecture

- Python `multiprocessing` is used to create N worker processes.
- Each worker starts its own Playwright instance and browser.
- A shared `multiprocessing.Queue` distributes URLs to workers. Workers pull URLs one at a time from the queue until they receive a sentinel value.
- This results in approximate round-robin distribution, though actual assignment depends on per-URL processing time.

### Container-level monitoring

A dedicated background thread samples container cgroup metrics every 500ms throughout the entire scaling run:
- `memory.current` (total container memory in bytes)
- Active memory: `anon + kernel` from `memory.stat`
- CPU utilization: derived from `cpu.stat usage_usec` delta over time

These timeline samples are saved in `scaling_meta.json` and can be exported as CSV for plotting.

### Per-worker tracking

For each worker, the following are recorded:
- Number of URLs processed
- Number of failures
- First and last URL wall times (for computing per-worker active duration)

### Configuration execution

All `(mode, worker_count)` configurations run sequentially in separate container invocations. This ensures each configuration has an isolated resource environment and measurements are not contaminated by concurrent configurations.

### Default test matrix

| Mode           | Worker counts      |
|----------------|--------------------|
| headful        | 1, 2, 3, 4        |
| headless-shell | 4, 8, 12, 16      |

Custom matrices can be specified via `--modes` and `--workers` flags.

## 7. Quality vs Performance Metrics

### Quality metrics

Quality metrics assess whether concurrent execution changes the data a browser returns for a given URL.

- **Page load success:** HTTP 200 response and `dom_complete_ms != -1` (page fully loaded).
- **Status code consistency:** HTTP status codes remain the same across worker counts.
- **Timeout rate:** Fraction of URLs that fail to load within the timeout.
- **Content completeness:** DOM element count, DOM byte size, visible text length, and network request count are compared against the single-worker baseline. Deviations above 10% are flagged as degradation; above 5% with timing or network anomalies are flagged as warnings.

Quality is summarized as a composite score (0-100) with weighted components:
- DOM score (30%): `min(actual/baseline, baseline/actual) * 100`
- Content score (30%): same formula applied to visible text length
- Network score (20%): `min(actual/baseline, 1.0) * 100`
- Timing score (20%): `min(baseline_time/actual_time, 1.0) * 100`

### Performance metrics

- **Wall time:** Total elapsed time from first worker start to last worker completion.
- **URLs per second:** `urls_ok / wall_time_s`.
- **Speedup:** `baseline_wall_time / current_wall_time` relative to the 1-worker configuration.
- **Efficiency:** `speedup / num_workers * 100%`. 100% indicates perfect linear scaling.
- **Peak memory:** Maximum `memory.current` observed in the cgroup timeline.
- **Peak active memory:** Maximum `anon + kernel` from cgroup `memory.stat`. This is the meaningful process-memory metric, as `memory.current` includes Linux page cache that accumulates monotonically.
- **CPU utilization:** Average and peak container CPU percentage derived from cgroup `cpu.stat`.

## 8. Reproducibility

The framework is designed for reproducible experiments:

- **Docker containers** ensure a consistent operating system, library, and browser environment across runs and machines.
- **`uv.lock`** pins all Python dependencies to exact versions. `uv sync --frozen` reproduces the identical dependency tree.
- **Same URL list** is used across all modes and worker counts within a job. URLs are loaded from a shared file and distributed identically.
- **Sequential container execution** eliminates host-level resource contention between modes or configurations.
- **Deterministic file naming** uses rank-prefixed slugs (`{rank}_{host}_{mode}.png`) to avoid collisions and enable per-URL comparison across runs.
- **cgroup v2 resource limits** (4 CPUs, 8 GB RAM) enforce a fixed resource budget regardless of host machine capacity.
- **Anti-detection parity** ensures all modes present the same browser fingerprint, so differences in server responses are not caused by bot detection treating modes differently.
