"""Browser-based data collection for a single URL visit."""

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil
from playwright.async_api import (
    Playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PwTimeout,
)

from . import config


# ── cgroup v2 readers (active only inside containers) ────────────────────

CGROUP_MEMORY_CURRENT = Path("/sys/fs/cgroup/memory.current")
CGROUP_MEMORY_STAT = Path("/sys/fs/cgroup/memory.stat")
CGROUP_CPU_STAT = Path("/sys/fs/cgroup/cpu.stat")

_CGROUP_AVAILABLE: bool | None = None


def _in_container() -> bool:
    """Detect whether we're running inside a cgroup v2 container."""
    global _CGROUP_AVAILABLE
    if _CGROUP_AVAILABLE is None:
        _CGROUP_AVAILABLE = CGROUP_MEMORY_CURRENT.exists() and CGROUP_CPU_STAT.exists()
    return _CGROUP_AVAILABLE


def _read_cgroup_int(path: Path) -> int:
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return -1


def _read_cgroup_cpu_usec() -> int:
    """Read total CPU usage in microseconds from cgroup cpu.stat."""
    try:
        for line in CGROUP_CPU_STAT.read_text().splitlines():
            if line.startswith("usage_usec"):
                return int(line.split()[1])
    except (FileNotFoundError, ValueError):
        pass
    return -1


def _read_cgroup_memory_stat() -> dict[str, int]:
    """Read key fields from cgroup memory.stat."""
    result = {}
    try:
        for line in CGROUP_MEMORY_STAT.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] in ("anon", "file", "kernel", "shmem", "sock"):
                result[parts[0]] = int(parts[1])
    except (FileNotFoundError, ValueError):
        pass
    return result

METRICS_JS = """
() => {
    const m = {};
    const bodyText = document.body ? document.body.innerText || '' : '';

    // Count every element tag name
    const tagCounts = {};
    for (const el of document.querySelectorAll('*')) {
        const tag = el.tagName.toLowerCase();
        tagCounts[tag] = (tagCounts[tag] || 0) + 1;
    }

    // Structural elements
    const structural = ['nav', 'main', 'footer', 'article', 'header', 'aside',
                        'section', 'form', 'table', 'dialog'];
    const structuralPresent = {};
    for (const tag of structural) {
        structuralPresent[tag] = (tagCounts[tag] || 0) > 0;
    }

    m.page_title = document.title || '';
    m.visible_text_length = bodyText.length;
    m.tag_counts = tagCounts;
    m.dom_element_count = document.querySelectorAll('*').length;
    m.dom_size_bytes = document.documentElement.outerHTML.length;
    m.structural_present = structuralPresent;

    // Resource Timing API
    const resources = performance.getEntriesByType('resource');
    m.resource_count = resources.length;
    let transferBytes = 0, decodedBytes = 0;
    const byInitiator = {};
    for (const r of resources) {
        transferBytes += r.transferSize || 0;
        decodedBytes += r.decodedBodySize || 0;
        const t = r.initiatorType || 'other';
        byInitiator[t] = (byInitiator[t] || 0) + 1;
    }
    m.total_transfer_bytes = transferBytes;
    m.total_decoded_bytes = decodedBytes;
    m.resources_by_initiator = byInitiator;

    // Navigation Timing
    const nav = performance.getEntriesByType('navigation')[0];
    if (nav) {
        m.dns_ms = nav.domainLookupEnd - nav.domainLookupStart;
        m.connect_ms = nav.connectEnd - nav.connectStart;
        m.ttfb_ms = nav.responseStart;
        m.response_ms = nav.responseEnd - nav.responseStart;
        m.dom_interactive_ms = nav.domInteractive > 0 ? nav.domInteractive : -1;
        m.dom_content_loaded_ms = nav.domContentLoadedEventEnd > 0 ? nav.domContentLoadedEventEnd : -1;
        m.dom_complete_ms = nav.domComplete > 0 ? nav.domComplete : -1;
        m.load_event_ms = nav.loadEventEnd > 0 ? nav.loadEventEnd : -1;
    }

    // Page dimensions
    m.document_height = Math.max(
        document.body ? document.body.scrollHeight : 0,
        document.documentElement ? document.documentElement.scrollHeight : 0
    );
    m.document_width = Math.max(
        document.body ? document.body.scrollWidth : 0,
        document.documentElement ? document.documentElement.scrollWidth : 0
    );

    return m;
}
"""

WEBDRIVER_PATCH = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
)


@dataclass
class PageMetrics:
    url: str
    final_url: str = ""
    mode: str = ""
    page_title: str = ""
    dom_element_count: int = 0
    dom_size_bytes: int = 0
    visible_text_length: int = 0
    tag_counts: dict[str, int] = field(default_factory=dict)
    structural_present: dict[str, bool] = field(default_factory=dict)
    request_counts_by_type: dict[str, int] = field(default_factory=dict)
    network_request_count: int = 0
    console_errors: list[str] = field(default_factory=list)
    screenshot_path: str = ""
    har_path: str = ""
    error: str = ""
    http_status: int = 0
    # Resource Timing API
    resource_count: int = 0
    total_transfer_bytes: int = 0
    total_decoded_bytes: int = 0
    resources_by_initiator: dict[str, int] = field(default_factory=dict)
    # Navigation Timing
    dns_ms: float = -1
    connect_ms: float = -1
    ttfb_ms: float = -1
    response_ms: float = -1
    dom_interactive_ms: float = -1
    dom_content_loaded_ms: float = -1
    dom_complete_ms: float = -1
    load_event_ms: float = -1
    # Page dimensions
    document_height: int = 0
    document_width: int = 0
    # Resource usage (across Chrome process tree) — before screenshot
    peak_rss_mb: float = 0.0
    peak_uss_mb: float = 0.0
    cpu_time_s: float = 0.0
    # Resource usage — after screenshot (includes compositing cost)
    rss_after_screenshot_mb: float = 0.0
    uss_after_screenshot_mb: float = 0.0
    cpu_time_with_screenshot_s: float = 0.0
    # Chrome process tree — averages and peaks from periodic sampling
    chrome_avg_rss_mb: float = 0.0
    chrome_avg_uss_mb: float = 0.0
    chrome_cpu_pct_avg: float = 0.0
    chrome_cpu_pct_peak: float = 0.0
    process_count_peak: int = 0
    # Container cgroup metrics (populated only when running in a container)
    container_active_memory_mb: float = 0.0    # avg (anon + kernel)
    container_total_memory_mb: float = 0.0     # avg memory.current
    container_cpu_pct: float = 0.0             # cgroup CPU %


_BROWSER_NAMES = {"chrome", "chrome-headless-shell", "chromium"}


def _find_browser_pid(browser: "Browser") -> int | None:
    """Find the Chrome root PID by inspecting Playwright's node server children."""
    try:
        node_pid = browser._impl_obj._connection._transport._proc.pid
        node_proc = psutil.Process(node_pid)
        for child in node_proc.children(recursive=False):
            try:
                if child.name().lower() in _BROWSER_NAMES:
                    return child.pid
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return None


def _get_process_tree(pid: int) -> list[psutil.Process]:
    """Return the process and all its descendants, ignoring already-gone pids."""
    try:
        parent = psutil.Process(pid)
        return [parent] + parent.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []


def _sample_resource_usage(pid: int) -> tuple[float, float]:
    """Sample total RSS and USS (MB) across the full process tree right now."""
    total_rss = 0.0
    total_uss = 0.0
    for proc in _get_process_tree(pid):
        try:
            mem = proc.memory_full_info()
            total_rss += mem.rss
            total_uss += mem.uss
        except (AttributeError, psutil.AccessDenied):
            # memory_full_info unavailable or denied — fall back to basic RSS
            try:
                total_rss += proc.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return total_rss / (1024 * 1024), total_uss / (1024 * 1024)


def _sample_cpu_times(pid: int) -> float:
    """Return total CPU time (user + system) across the process tree in seconds."""
    total = 0.0
    for proc in _get_process_tree(pid):
        try:
            ct = proc.cpu_times()
            total += ct.user + ct.system
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return total


def _sample_chrome_tree(proc: psutil.Process) -> tuple[int, int, int, float]:
    """Sample Chrome process tree. Returns (num_procs, total_rss_bytes, total_uss_bytes, total_cpu_secs)."""
    try:
        children = proc.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return (0, 0, 0, 0.0)

    all_procs = [proc] + children
    total_rss = 0
    total_uss = 0
    total_cpu_secs = 0.0
    live = 0

    for p in all_procs:
        try:
            mem = p.memory_full_info()
            total_rss += mem.rss
            total_uss += mem.uss
            ct = p.cpu_times()
            total_cpu_secs += ct.user + ct.system
            live += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            try:
                mem = p.memory_info()
                total_rss += mem.rss
                ct = p.cpu_times()
                total_cpu_secs += ct.user + ct.system
                live += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        except psutil.ZombieProcess:
            continue

    return (live, total_rss, total_uss, total_cpu_secs)


async def _sample_resources_periodically(
    pid: int,
    interval: float,
    stop_event: asyncio.Event,
    results: dict,
) -> None:
    """Background task that samples Chrome tree + cgroup metrics until stop_event."""
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return

    in_ctr = _in_container()

    # Baseline readings
    prev_cpu_secs = 0.0
    prev_time = time.monotonic()
    baseline = _sample_chrome_tree(proc)
    if baseline[0] > 0:
        prev_cpu_secs = baseline[3]

    cgroup_cpu_start = _read_cgroup_cpu_usec() if in_ctr else -1
    t0 = time.monotonic()

    await asyncio.sleep(interval)

    # Accumulators
    rss_samples: list[float] = []
    uss_samples: list[float] = []
    cpu_pct_samples: list[float] = []
    process_count_peak = 0
    cgroup_mem_samples: list[float] = []      # memory.current in MB
    cgroup_active_samples: list[float] = []   # (anon + kernel) in MB

    def _take_sample():
        nonlocal prev_cpu_secs, prev_time, process_count_peak

        num_procs, rss_bytes, uss_bytes, cpu_secs = _sample_chrome_tree(proc)
        if num_procs == 0:
            return

        now = time.monotonic()
        dt = now - prev_time
        cpu_pct = max(0.0, ((cpu_secs - prev_cpu_secs) / dt) * 100) if dt > 0 else 0.0
        prev_cpu_secs = cpu_secs
        prev_time = now

        rss_mb = rss_bytes / (1024 * 1024)
        uss_mb = uss_bytes / (1024 * 1024)
        rss_samples.append(rss_mb)
        uss_samples.append(uss_mb)
        cpu_pct_samples.append(cpu_pct)
        process_count_peak = max(process_count_peak, num_procs)

        if in_ctr:
            mem_bytes = _read_cgroup_int(CGROUP_MEMORY_CURRENT)
            if mem_bytes >= 0:
                cgroup_mem_samples.append(mem_bytes / (1024 * 1024))
            mem_stat = _read_cgroup_memory_stat()
            anon = mem_stat.get("anon", -1)
            kernel = mem_stat.get("kernel", -1)
            if anon >= 0 and kernel >= 0:
                cgroup_active_samples.append((anon + kernel) / (1024 * 1024))

    while not stop_event.is_set():
        _take_sample()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass

    # Final sample
    _take_sample()

    duration = time.monotonic() - t0

    # Chrome tree aggregates
    results["peak_rss_mb"] = max(rss_samples) if rss_samples else 0.0
    results["peak_uss_mb"] = max(uss_samples) if uss_samples else 0.0
    results["chrome_avg_rss_mb"] = sum(rss_samples) / len(rss_samples) if rss_samples else 0.0
    results["chrome_avg_uss_mb"] = sum(uss_samples) / len(uss_samples) if uss_samples else 0.0
    results["chrome_cpu_pct_avg"] = sum(cpu_pct_samples) / len(cpu_pct_samples) if cpu_pct_samples else 0.0
    results["chrome_cpu_pct_peak"] = max(cpu_pct_samples) if cpu_pct_samples else 0.0
    results["process_count_peak"] = process_count_peak

    # Container cgroup aggregates
    if in_ctr:
        results["container_total_memory_mb"] = (
            sum(cgroup_mem_samples) / len(cgroup_mem_samples) if cgroup_mem_samples else 0.0
        )
        results["container_active_memory_mb"] = (
            sum(cgroup_active_samples) / len(cgroup_active_samples) if cgroup_active_samples else 0.0
        )
        cgroup_cpu_end = _read_cgroup_cpu_usec()
        if cgroup_cpu_start >= 0 and cgroup_cpu_end >= 0 and duration > 0:
            results["container_cpu_pct"] = (
                (cgroup_cpu_end - cgroup_cpu_start) / (duration * 1_000_000) * 100
            )


async def collect_page_data(
    pw: Playwright,
    url: str,
    mode: str,
    output_dir: Path,
    host_slug: str,
    rank: int = 0,
) -> PageMetrics:
    """Visit url in the given mode and collect metrics, screenshot, and HAR."""
    mode_cfg = config.MODE_CONFIG[mode]
    metrics = PageMetrics(url=url, mode=mode)

    # Include rank in filenames to avoid collisions for duplicate hosts
    file_slug = f"{rank:04d}_{host_slug}" if rank else host_slug
    har_filename = f"{file_slug}_{mode}.har"
    har_path = output_dir / "har" / har_filename
    screenshot_filename = f"{file_slug}_{mode}.png"
    screenshot_path = output_dir / "screenshots" / screenshot_filename

    browser: Browser | None = None
    context: BrowserContext | None = None
    page: Page | None = None
    resource_stop = asyncio.Event()
    resource_results: dict = {}
    sampler_task: asyncio.Task | None = None
    browser_pid: int | None = None
    cpu_start = 0.0
    try:
        browser = await pw.chromium.launch(
            headless=mode_cfg["headless"],
            channel=mode_cfg["channel"],
            args=mode_cfg["args"],
            timeout=30_000,
        )

        # Start resource sampling on the browser's process tree
        browser_pid = _find_browser_pid(browser)
        if browser_pid:
            cpu_start = _sample_cpu_times(browser_pid)
            sampler_task = asyncio.create_task(
                _sample_resources_periodically(
                    browser_pid, 0.25, resource_stop, resource_results
                )
            )

        ctx_opts: dict = {
            "viewport": config.VIEWPORT,
            "record_har_path": str(har_path),
            "record_har_omit_content": True,
        }
        ctx_opts["user_agent"] = mode_cfg["user_agent"]
        context = await browser.new_context(**ctx_opts)
        page = await context.new_page()

        # Hide navigator.webdriver signal
        await page.add_init_script(WEBDRIVER_PATCH)

        console_errors: list[str] = []
        page.on(
            "console",
            lambda msg: console_errors.append(msg.text)
            if msg.type == "error"
            else None,
        )

        request_count = 0
        request_type_counts: dict[str, int] = {}

        def _on_request(req):
            nonlocal request_count
            request_count += 1
            rtype = req.resource_type
            request_type_counts[rtype] = request_type_counts.get(rtype, 0) + 1

        page.on("request", _on_request)

        # Navigate — timeout is non-fatal, we collect whatever loaded
        response = None
        try:
            response = await page.goto(
                url,
                wait_until=config.WAIT_UNTIL,
                timeout=config.PAGE_TIMEOUT_MS,
            )
        except PwTimeout:
            pass  # page partially loaded — continue to metrics

        # Brief settle for dynamic content
        await asyncio.sleep(config.SETTLE_TIME_S)

        metrics.http_status = response.status if response else 0
        metrics.final_url = page.url
        metrics.network_request_count = request_count
        metrics.request_counts_by_type = request_type_counts
        metrics.console_errors = console_errors[:20]

        # Collect DOM + resource + timing metrics
        try:
            js_data = await page.evaluate(METRICS_JS)
            metrics.page_title = js_data["page_title"]
            metrics.dom_element_count = js_data["dom_element_count"]
            metrics.dom_size_bytes = js_data["dom_size_bytes"]
            metrics.visible_text_length = js_data["visible_text_length"]
            metrics.tag_counts = js_data["tag_counts"]
            metrics.structural_present = js_data["structural_present"]
            # Resource Timing API
            metrics.resource_count = js_data.get("resource_count", 0)
            metrics.total_transfer_bytes = js_data.get("total_transfer_bytes", 0)
            metrics.total_decoded_bytes = js_data.get("total_decoded_bytes", 0)
            metrics.resources_by_initiator = js_data.get("resources_by_initiator", {})
            # Navigation Timing
            metrics.dns_ms = js_data.get("dns_ms", -1)
            metrics.connect_ms = js_data.get("connect_ms", -1)
            metrics.ttfb_ms = js_data.get("ttfb_ms", -1)
            metrics.response_ms = js_data.get("response_ms", -1)
            metrics.dom_interactive_ms = js_data.get("dom_interactive_ms", -1)
            metrics.dom_content_loaded_ms = js_data.get("dom_content_loaded_ms", -1)
            metrics.dom_complete_ms = js_data.get("dom_complete_ms", -1)
            metrics.load_event_ms = js_data.get("load_event_ms", -1)
            # Page dimensions
            metrics.document_height = js_data.get("document_height", 0)
            metrics.document_width = js_data.get("document_width", 0)
        except Exception:
            metrics.error = "JS evaluation failed"

    except Exception as e:
        metrics.error = str(e)[:200]
        del e
    finally:
        # Stop resource sampler and collect final readings
        if sampler_task is not None:
            resource_stop.set()
            try:
                await asyncio.wait_for(sampler_task, timeout=5.0)
            except Exception:
                sampler_task.cancel()
            metrics.peak_rss_mb = resource_results.get("peak_rss_mb", 0.0)
            metrics.peak_uss_mb = resource_results.get("peak_uss_mb", 0.0)
            metrics.chrome_avg_rss_mb = resource_results.get("chrome_avg_rss_mb", 0.0)
            metrics.chrome_avg_uss_mb = resource_results.get("chrome_avg_uss_mb", 0.0)
            metrics.chrome_cpu_pct_avg = resource_results.get("chrome_cpu_pct_avg", 0.0)
            metrics.chrome_cpu_pct_peak = resource_results.get("chrome_cpu_pct_peak", 0.0)
            metrics.process_count_peak = resource_results.get("process_count_peak", 0)
            metrics.container_active_memory_mb = resource_results.get("container_active_memory_mb", 0.0)
            metrics.container_total_memory_mb = resource_results.get("container_total_memory_mb", 0.0)
            metrics.container_cpu_pct = resource_results.get("container_cpu_pct", 0.0)
            if browser_pid:
                try:
                    cpu_end = _sample_cpu_times(browser_pid)
                    metrics.cpu_time_s = cpu_end - cpu_start
                except Exception:
                    pass

        # Always capture screenshot if page exists
        if page is not None:
            try:
                await asyncio.wait_for(
                    page.screenshot(path=str(screenshot_path), full_page=False),
                    timeout=15,
                )
                metrics.screenshot_path = screenshot_filename
            except Exception:
                pass

        # Second resource sample: includes screenshot compositing cost
        if browser_pid:
            try:
                cpu_after_screenshot = _sample_cpu_times(browser_pid)
                metrics.cpu_time_with_screenshot_s = cpu_after_screenshot - cpu_start
                rss, uss = _sample_resource_usage(browser_pid)
                metrics.rss_after_screenshot_mb = rss
                metrics.uss_after_screenshot_mb = uss
            except Exception:
                pass

        # Close page explicitly to release event listeners
        if page is not None:
            try:
                await asyncio.wait_for(page.close(), timeout=5)
            except Exception:
                pass

        # Close context to flush HAR file
        if context is not None:
            try:
                await asyncio.wait_for(context.close(), timeout=10)
                metrics.har_path = har_filename
            except Exception:
                pass

        if browser is not None:
            try:
                await asyncio.wait_for(browser.close(), timeout=10)
            except Exception:
                pass

    return metrics
