"""Configuration and CLI argument parsing."""

import argparse
from pathlib import Path

# Paths
DEFAULT_INPUT = Path("urls.md")
DEFAULT_OUTPUT_DIR = Path("output")

# Browser settings
CHANNEL = "chrome"
VIEWPORT = {"width": 1280, "height": 720}
BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
]

# Match the real headful Chrome UA so headless doesn't leak "HeadlessChrome"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
)

# Centralised mode → Playwright launch parameters mapping.
MODE_CONFIG = {
    "headful": {
        "headless": False,
        "channel": CHANNEL,
        "args": BROWSER_ARGS,
        "user_agent": USER_AGENT,
    },
    "headless": {
        "headless": True,
        "channel": CHANNEL,
        "args": BROWSER_ARGS,
        "user_agent": USER_AGENT,
    },
    "headless-shell": {
        "headless": True,
        "channel": "chromium-headless-shell",
        "args": BROWSER_ARGS,
        "user_agent": USER_AGENT,
    },
}

DEFAULT_MODES = ["headful", "headless"]

# Timing — cap load at 10s, then collect whatever rendered
PAGE_TIMEOUT_MS = 10_000
SETTLE_TIME_S = 2.0
WAIT_UNTIL = "domcontentloaded"

# Batching
DEFAULT_TOP_N = 50
BATCH_SIZE = 10

# Diff thresholds
SCREENSHOT_DIFF_THRESHOLD = 0.05  # 5% pixel difference
DOM_COUNT_RATIO_THRESHOLD = 0.20  # 20% element count diff
DOM_SIZE_RATIO_THRESHOLD = 0.20  # 20% serialized HTML size diff
CONTENT_LENGTH_RATIO_THRESHOLD = 0.20


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare headless vs headful rendering for ranked URLs",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Path to the top_diffs_rendering.md file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for results and screenshots",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=None,
        help="Number of top-ranked URLs to process (default: all for --url-list, "
        f"{DEFAULT_TOP_N} for markdown input)",
    )
    parser.add_argument(
        "--start-rank",
        type=int,
        default=1,
        help="Start from this rank (for resuming)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help="URLs per batch",
    )
    parser.add_argument(
        "--url-list",
        type=Path,
        default=None,
        help="Plain-text file with one URL per line (alternative to markdown/CSV input)",
    )
    parser.add_argument(
        "--csv-input",
        type=Path,
        default=None,
        help="Path to a results.csv from a previous run. "
        "When provided, URLs are read from this CSV instead of the markdown ranking file.",
    )
    parser.add_argument(
        "--filter-diff-types",
        type=str,
        nargs="*",
        default=None,
        help="Only re-run URLs with these diff_type values (e.g., missing_content dom_diff). "
        "Only used with --csv-input.",
    )
    parser.add_argument(
        "--min-net-req-diff",
        type=int,
        default=None,
        help="Only re-run URLs where |network_request_diff| >= this value. "
        "Only used with --csv-input.",
    )
    parser.add_argument(
        "--full-better",
        action="store_true",
        default=True,
        help="Only include URLs where full mode rendered more DOM (default)",
    )
    parser.add_argument(
        "--all-urls",
        action="store_true",
        help="Include all URLs regardless of which mode rendered more",
    )
    parser.add_argument(
        "--modes",
        default=",".join(DEFAULT_MODES),
        help="Comma-separated browser modes to test (default: headful,headless). "
        "Available: " + ", ".join(MODE_CONFIG),
    )
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Run data collection for the specified modes only (no comparison). "
        "Saves raw_metrics_{mode}.json per mode. Used by Docker containers.",
    )
    parser.add_argument(
        "--merge-report",
        action="store_true",
        help="Load per-mode raw_metrics_{mode}.json files from --output dir, "
        "merge them, run comparison against headful, and generate reports.",
    )
    parser.add_argument(
        "--diff-pairs",
        type=str,
        default=None,
        help="Comma-separated pairs for diff image generation, e.g. 'HL-HF,HS-HF'. "
        "Abbreviations: HL=headless, HF=headful, HS=headless-shell. "
        "If omitted, no diff images are generated.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of concurrent browser worker processes (default: 1, sequential)",
    )
    return parser
