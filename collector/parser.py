"""Parse URL inputs from various formats (markdown table, CSV, plain-text list)."""

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|")


@dataclass
class RankedURL:
    rank: int
    host: str
    score: float = 0.0
    tech_diff: int = 0
    dom_ratio: float = 0.0
    h_dom_size: int = 0
    f_dom_size: int = 0
    req_diff: int = 0
    other_diff: int = 0
    cluster: str = ""
    full_url: str = ""

    @property
    def url(self) -> str:
        return self.full_url or f"https://{self.host}"


def _parse_int(s: str) -> int:
    return int(s.replace(",", "").strip())


def parse_ranking_file(
    path: Path,
    top_n: int | None = None,
    start_rank: int = 1,
    full_better_only: bool = False,
) -> list[RankedURL]:
    """Parse markdown table rows into RankedURL objects.

    Args:
        full_better_only: If True, keep only URLs where the full (GUI) browser
            rendered a larger DOM than headless — the strongest candidates for
            headless rendering gaps.  top_n is applied *after* this filter.
    """
    all_rows: list[RankedURL] = []
    text = path.read_text()

    for line in text.splitlines():
        m = ROW_RE.match(line)
        if not m:
            continue

        cells = [c.strip() for c in line.split("|")]
        cells = [c for c in cells if c]

        if len(cells) < 10:
            continue

        all_rows.append(
            RankedURL(
                rank=int(cells[0]),
                host=cells[1].strip(),
                score=float(cells[2]),
                tech_diff=int(cells[3]),
                dom_ratio=float(cells[4]),
                h_dom_size=_parse_int(cells[5]),
                f_dom_size=_parse_int(cells[6]),
                req_diff=int(cells[7]),
                other_diff=int(cells[8]),
                cluster=cells[9].strip(),
            )
        )

    if full_better_only:
        all_rows = [u for u in all_rows if u.f_dom_size > u.h_dom_size]

    # Sort by score descending (already is, but enforce after filtering)
    all_rows.sort(key=lambda u: u.score, reverse=True)

    # Apply start offset and limit
    start_idx = start_rank - 1
    if top_n is not None:
        return all_rows[start_idx : start_idx + top_n]
    return all_rows[start_idx:]


def parse_csv_results(
    csv_path: Path,
    diff_types: list[str] | None = None,
    min_net_req_diff: int | None = None,
) -> list[RankedURL]:
    """Load URLs from a previous results.csv, optionally filtering.

    Filters are combined with OR logic: a URL is included if it matches
    ANY of the provided filter criteria.
    """
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))

    has_any_filter = diff_types is not None or min_net_req_diff is not None
    selected: list[RankedURL] = []
    seen_hosts: set[str] = set()

    for row in rows:
        if has_any_filter:
            match = False
            if diff_types and row["diff_type"] in diff_types:
                match = True
            if min_net_req_diff is not None:
                try:
                    if abs(int(row["network_request_diff"])) >= min_net_req_diff:
                        match = True
                except (ValueError, KeyError):
                    pass
            if not match:
                continue

        host = row["host"]
        if host in seen_hosts:
            continue
        seen_hosts.add(host)

        selected.append(
            RankedURL(
                rank=int(row["rank"]),
                host=host,
                score=float(row.get("severity", 0) or 0),
                tech_diff=0,
                dom_ratio=float(row.get("dom_count_ratio", 0) or 0),
                h_dom_size=0,
                f_dom_size=0,
                req_diff=int(row.get("network_request_diff", 0) or 0),
                other_diff=0,
                cluster=row.get("diff_type", ""),
            )
        )

    selected.sort(key=lambda u: u.score, reverse=True)
    return selected


def parse_url_list(
    path: Path,
    top_n: int | None = None,
    start_rank: int = 1,
) -> list[RankedURL]:
    """Parse a plain-text file with one URL per line.

    Skips blank lines and lines starting with '#'.
    Assigns sequential ranks starting from start_rank.
    """
    all_urls: list[RankedURL] = []

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parsed = urlparse(line)
        host = parsed.hostname or line
        all_urls.append(
            RankedURL(
                rank=len(all_urls) + 1,
                host=host,
                full_url=line,
            )
        )

    # Apply start offset and limit
    start_idx = start_rank - 1
    if top_n is not None:
        return all_urls[start_idx : start_idx + top_n]
    return all_urls[start_idx:]
