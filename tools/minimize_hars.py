#!/usr/bin/env python3
"""Strip HTTP response bodies from HAR files to reclaim disk space.

Removes `response.content.text` (and `encoding`) from every entry while
keeping all other metadata (URLs, timings, headers, sizes, mimeTypes).

Usage:
    python minimize_hars.py output/              # minimize all HARs under output/
    python minimize_hars.py output/ --dry-run     # report savings without modifying files
    python minimize_hars.py output/ --workers 8   # control parallelism
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path


def find_har_files(root: Path) -> list[Path]:
    hars = []
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if f.endswith(".har"):
                hars.append(Path(dirpath) / f)
    return hars


def minimize_har(args: tuple[Path, bool]) -> tuple[str, int, int, bool]:
    """Process a single HAR file. Returns (path, old_size, new_size, modified)."""
    path, dry_run = args
    old_size = path.stat().st_size

    try:
        with open(path, "r") as f:
            har = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  SKIP {path}: {e}", file=sys.stderr)
        return (str(path), old_size, old_size, False)

    modified = False
    for entry in har.get("log", {}).get("entries", []):
        content = entry.get("response", {}).get("content", {})
        if "text" in content:
            del content["text"]
            modified = True
        if "encoding" in content:
            del content["encoding"]
            modified = True

    if not modified:
        return (str(path), old_size, old_size, False)

    if dry_run:
        new_bytes = len(json.dumps(har, separators=(",", ":")).encode())
        return (str(path), old_size, new_bytes, True)

    tmp_path = path.with_suffix(".har.tmp")
    with open(tmp_path, "w") as f:
        json.dump(har, f, separators=(",", ":"))
    tmp_path.replace(path)
    new_size = path.stat().st_size

    return (str(path), old_size, new_size, True)


def fmt_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} PB"


def main():
    parser = argparse.ArgumentParser(description="Minimize HAR files by removing response bodies")
    parser.add_argument("path", type=Path, help="Root directory to scan for .har files")
    parser.add_argument("--dry-run", action="store_true", help="Report savings without modifying files")
    parser.add_argument("--workers", type=int, default=cpu_count(), help="Number of parallel workers")
    args = parser.parse_args()

    if not args.path.is_dir():
        print(f"Error: {args.path} is not a directory", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {args.path} for .har files...")
    har_files = find_har_files(args.path)
    print(f"Found {len(har_files)} HAR files")

    if not har_files:
        return

    mode = "DRY RUN" if args.dry_run else "MINIMIZING"
    print(f"{mode} with {args.workers} workers...\n")

    total_old = 0
    total_new = 0
    files_modified = 0
    files_skipped = 0

    work = [(p, args.dry_run) for p in har_files]

    with Pool(processes=args.workers) as pool:
        for i, (path, old_size, new_size, modified) in enumerate(
            pool.imap_unordered(minimize_har, work, chunksize=32), 1
        ):
            total_old += old_size
            total_new += new_size
            if modified:
                files_modified += 1
                saved = old_size - new_size
                print(f"  [{i}/{len(har_files)}] {path}: {fmt_size(old_size)} -> {fmt_size(new_size)} (saved {fmt_size(saved)})")
            else:
                files_skipped += 1
                if i % 500 == 0:
                    print(f"  [{i}/{len(har_files)}] progress... ({files_skipped} already minimal)")

    saved = total_old - total_new
    print(f"\n{'DRY RUN ' if args.dry_run else ''}Summary:")
    print(f"  Files processed:  {files_modified + files_skipped}")
    print(f"  Files modified:   {files_modified}")
    print(f"  Files skipped:    {files_skipped} (already minimal)")
    print(f"  Before:           {fmt_size(total_old)}")
    print(f"  After:            {fmt_size(total_new)}")
    print(f"  Saved:            {fmt_size(saved)} ({saved / total_old * 100:.1f}%)" if total_old else "")


if __name__ == "__main__":
    main()
