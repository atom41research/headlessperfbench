"""Compare headless vs headful metrics and compute diff scores."""

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from . import config
from .collector import PageMetrics

MODE_ABBREV = {"headless": "HL", "headful": "HF", "headless-shell": "HS"}


@dataclass
class ComparisonResult:
    host: str
    url: str
    rank: int
    # Flags
    has_screenshot_diff: bool = False
    has_dom_count_diff: bool = False
    has_dom_size_diff: bool = False
    has_content_length_diff: bool = False
    has_structural_diff: bool = False
    has_title_diff: bool = False
    has_redirect_diff: bool = False
    # Numeric diffs
    screenshot_diff_pct: float = 0.0
    dom_count_ratio: float = 0.0
    dom_size_ratio: float = 0.0
    content_length_ratio: float = 0.0
    network_request_diff: int = 0
    # Per-tag element count diffs: tag -> (headless_count, headful_count)
    tag_count_diffs: dict[str, tuple[int, int]] = field(default_factory=dict)
    # Request type diffs: type -> (headless_count, headful_count)
    request_type_diffs: dict[str, tuple[int, int]] = field(default_factory=dict)
    # Structural elements only in one mode
    elements_only_headful: list[str] = field(default_factory=list)
    elements_only_headless: list[str] = field(default_factory=list)
    # Console errors
    headless_console_errors: int = 0
    headful_console_errors: int = 0
    # Severity score
    severity: float = 0.0
    # Errors
    headless_error: str = ""
    headful_error: str = ""
    # Category
    diff_type: str = ""
    # Resource timing diffs
    resource_count_diff: int = 0
    transfer_bytes_diff: int = 0
    # Page dimension diffs
    document_height_diff: int = 0
    document_width_diff: int = 0
    # Which non-headful mode was compared (e.g. "headless" or "headless-shell")
    compared_mode: str = "headless"
    # Resource usage per mode (absolute values, not diffs)
    headless_peak_rss_mb: float = 0.0
    headless_peak_uss_mb: float = 0.0
    headless_cpu_time_s: float = 0.0
    headless_cpu_time_with_screenshot_s: float = 0.0
    headless_rss_after_screenshot_mb: float = 0.0
    headless_uss_after_screenshot_mb: float = 0.0
    headful_peak_rss_mb: float = 0.0
    headful_peak_uss_mb: float = 0.0
    headful_cpu_time_s: float = 0.0
    headful_cpu_time_with_screenshot_s: float = 0.0
    headful_rss_after_screenshot_mb: float = 0.0
    headful_uss_after_screenshot_mb: float = 0.0


def compute_screenshot_diff(path_a: Path, path_b: Path) -> float:
    """Return fraction of pixels that differ between two screenshots."""
    try:
        img_a = np.array(Image.open(path_a).convert("RGB"), dtype=np.int16)
        img_b = np.array(Image.open(path_b).convert("RGB"), dtype=np.int16)

        h = min(img_a.shape[0], img_b.shape[0])
        w = min(img_a.shape[1], img_b.shape[1])
        img_a = img_a[:h, :w]
        img_b = img_b[:h, :w]

        diff = np.abs(img_a - img_b)
        pixel_diff = np.any(diff > 25, axis=2)
        return float(pixel_diff.sum()) / float(pixel_diff.size)
    except Exception:
        return 0.0


def generate_diff_image(path_a: Path, path_b: Path, output_path: Path) -> None:
    """Create a visual diff image highlighting changed pixels in red."""
    try:
        img_a = np.array(Image.open(path_a).convert("RGB"), dtype=np.int16)
        img_b = np.array(Image.open(path_b).convert("RGB"), dtype=np.int16)

        h = min(img_a.shape[0], img_b.shape[0])
        w = min(img_a.shape[1], img_b.shape[1])
        img_a = img_a[:h, :w]
        img_b = img_b[:h, :w]

        diff = np.abs(img_a - img_b)
        changed = np.any(diff > 25, axis=2)

        result = img_b.copy().astype(np.uint8)
        result[changed] = [255, 0, 0]

        Image.fromarray(result).save(output_path)
    except Exception:
        pass


def _diff_dicts(
    hl: dict[str, int], hf: dict[str, int]
) -> dict[str, tuple[int, int]]:
    """Return keys where values differ, with (headless, headful) counts."""
    all_keys = set(hl) | set(hf)
    diffs: dict[str, tuple[int, int]] = {}
    for key in sorted(all_keys):
        hl_val = hl.get(key, 0)
        hf_val = hf.get(key, 0)
        if hl_val != hf_val:
            diffs[key] = (hl_val, hf_val)
    return diffs


def compare(
    headless: PageMetrics,
    headful: PageMetrics,
    host: str,
    rank: int,
    screenshots_dir: Path,
    generate_diff: bool = False,
) -> ComparisonResult:
    """Compare two PageMetrics and produce a ComparisonResult."""
    result = ComparisonResult(host=host, url=headless.url, rank=rank)
    result.headless_error = headless.error
    result.headful_error = headful.error

    if headless.error and headful.error:
        result.diff_type = "both_errored"
        return result
    if headless.error:
        result.diff_type = "headless_errored"
        result.severity = 100.0
        return result
    if headful.error:
        result.diff_type = "headful_errored"
        result.severity = 100.0
        return result

    # Screenshot diff
    hl_ss = screenshots_dir / headless.screenshot_path
    hf_ss = screenshots_dir / headful.screenshot_path
    if hl_ss.exists() and hf_ss.exists():
        result.screenshot_diff_pct = compute_screenshot_diff(hl_ss, hf_ss)
        result.has_screenshot_diff = (
            result.screenshot_diff_pct > config.SCREENSHOT_DIFF_THRESHOLD
        )
        if result.has_screenshot_diff and generate_diff:
            slug = f"{rank:04d}_{host.replace('.', '_')}"
            a_abbrev = MODE_ABBREV.get(headless.mode, headless.mode)
            b_abbrev = MODE_ABBREV.get(headful.mode, headful.mode)
            diff_name = f"{slug}_{a_abbrev}_vs_{b_abbrev}_diff.png"
            generate_diff_image(hl_ss, hf_ss, screenshots_dir / diff_name)

    # DOM element count ratio (log2)
    if headless.dom_element_count > 0 and headful.dom_element_count > 0:
        result.dom_count_ratio = math.log2(
            headful.dom_element_count / headless.dom_element_count
        )
        result.has_dom_count_diff = abs(result.dom_count_ratio) > math.log2(
            1 + config.DOM_COUNT_RATIO_THRESHOLD
        )

    # DOM serialized size ratio (log2)
    if headless.dom_size_bytes > 0 and headful.dom_size_bytes > 0:
        result.dom_size_ratio = math.log2(
            headful.dom_size_bytes / headless.dom_size_bytes
        )
        result.has_dom_size_diff = abs(result.dom_size_ratio) > math.log2(
            1 + config.DOM_SIZE_RATIO_THRESHOLD
        )

    # Content length ratio (log2)
    if headless.visible_text_length > 0 and headful.visible_text_length > 0:
        result.content_length_ratio = math.log2(
            headful.visible_text_length / headless.visible_text_length
        )
        result.has_content_length_diff = abs(result.content_length_ratio) > math.log2(
            1 + config.CONTENT_LENGTH_RATIO_THRESHOLD
        )

    # Per-tag element count diffs
    result.tag_count_diffs = _diff_dicts(headless.tag_counts, headful.tag_counts)

    # Request type diffs
    result.request_type_diffs = _diff_dicts(
        headless.request_counts_by_type, headful.request_counts_by_type
    )

    # Network request total diff
    result.network_request_diff = (
        headful.network_request_count - headless.network_request_count
    )

    # Resource timing diffs
    result.resource_count_diff = headful.resource_count - headless.resource_count
    result.transfer_bytes_diff = (
        headful.total_transfer_bytes - headless.total_transfer_bytes
    )

    # Page dimension diffs
    result.document_height_diff = headful.document_height - headless.document_height
    result.document_width_diff = headful.document_width - headless.document_width

    # Structural elements
    hl_struct = headless.structural_present
    hf_struct = headful.structural_present
    all_structural = set(hl_struct) | set(hf_struct)
    for el in sorted(all_structural):
        hl_has = hl_struct.get(el, False)
        hf_has = hf_struct.get(el, False)
        if hf_has and not hl_has:
            result.elements_only_headful.append(el)
        if hl_has and not hf_has:
            result.elements_only_headless.append(el)
    result.has_structural_diff = bool(
        result.elements_only_headful or result.elements_only_headless
    )

    # Title diff
    result.has_title_diff = headless.page_title != headful.page_title

    # Redirect diff
    result.has_redirect_diff = headless.final_url != headful.final_url

    # Console errors
    result.headless_console_errors = len(headless.console_errors)
    result.headful_console_errors = len(headful.console_errors)

    # Resource usage (store absolute values for both modes)
    result.headless_peak_rss_mb = headless.peak_rss_mb
    result.headless_peak_uss_mb = headless.peak_uss_mb
    result.headless_cpu_time_s = headless.cpu_time_s
    result.headless_cpu_time_with_screenshot_s = headless.cpu_time_with_screenshot_s
    result.headless_rss_after_screenshot_mb = headless.rss_after_screenshot_mb
    result.headless_uss_after_screenshot_mb = headless.uss_after_screenshot_mb
    result.headful_peak_rss_mb = headful.peak_rss_mb
    result.headful_peak_uss_mb = headful.peak_uss_mb
    result.headful_cpu_time_s = headful.cpu_time_s
    result.headful_cpu_time_with_screenshot_s = headful.cpu_time_with_screenshot_s
    result.headful_rss_after_screenshot_mb = headful.rss_after_screenshot_mb
    result.headful_uss_after_screenshot_mb = headful.uss_after_screenshot_mb

    # Composite severity score
    tag_diff_magnitude = sum(
        abs(hf - hl) for hl, hf in result.tag_count_diffs.values()
    )
    req_diff_magnitude = sum(
        abs(hf - hl) for hl, hf in result.request_type_diffs.values()
    )

    result.severity = (
        30 * result.screenshot_diff_pct
        + 15 * min(abs(result.dom_count_ratio), 5.0)
        + 5 * min(abs(result.dom_size_ratio), 5.0)
        + 15 * min(abs(result.content_length_ratio), 5.0)
        + 10 * (1 if result.has_structural_diff else 0)
        + 5 * (1 if result.has_title_diff else 0)
        + 5 * (1 if result.has_redirect_diff else 0)
        + 5 * min(tag_diff_magnitude / 100, 5.0)
        + 5 * min(req_diff_magnitude / 20, 5.0)
    )

    # Categorize
    if result.has_redirect_diff:
        result.diff_type = "redirect_diff"
    elif result.has_dom_count_diff and result.has_screenshot_diff:
        result.diff_type = "missing_content"
    elif result.has_screenshot_diff:
        result.diff_type = "layout_diff"
    elif result.has_dom_count_diff:
        result.diff_type = "dom_diff"
    elif result.has_structural_diff:
        result.diff_type = "structural_diff"
    elif result.has_title_diff:
        result.diff_type = "title_diff"
    else:
        result.diff_type = "identical"

    return result
