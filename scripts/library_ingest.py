#!/usr/bin/env python3
"""Copy a raw source into <library>/sources/ and log the ingest.

The Python side is intentionally minimal: file copy + log append. The
slash command's Markdown body drives the LLM-side work of reading the
source and proposing memories/skills/context updates.

URLs are not fetched here. The slash command fetches via WebFetch and
hands a local path to this script.

Usage:
    python scripts/library_ingest.py --source <local-path> \
        [--title "..."] [--library /path] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import common
import library_log
import scan_secrets


def _sanitize_filename(source: Path, title: str | None, now: datetime) -> str:
    base = title or source.stem
    slug = common.slugify(base)
    if not slug:
        slug = "source"
    ext = source.suffix.lower()
    if not ext:
        ext = ".md"
    return f"{now.strftime('%Y-%m-%d')}-{slug}{ext}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest a source into the library.")
    parser.add_argument("--source", required=True, help="Local path to the source file.")
    parser.add_argument("--title", default=None, help="Optional title; derived from filename otherwise.")
    parser.add_argument("--library", default=None, help="Library root (defaults to $AI_CONTEXT_LIBRARY_PATH or cwd).")
    parser.add_argument("--dry-run", action="store_true", help="Print the would-be destination and exit.")
    args = parser.parse_args(argv)

    source = Path(args.source).expanduser().resolve()
    if not source.exists() or not source.is_file():
        print(f"error: source does not exist or is not a file: {source}", file=sys.stderr)
        return 2

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    sources_dir = library / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    dest_name = _sanitize_filename(source, args.title, now)
    dest = sources_dir / dest_name

    if args.dry_run:
        print(f"would copy: {source} -> {dest}")
        print(f"would log:  ingest | {dest_name}")
        return 0

    if dest.exists():
        print(f"error: refusing to overwrite existing source: {dest}", file=sys.stderr)
        return 1

    # Copy to a tempfile OUTSIDE the library tree so directory-watching
    # syncs never see content that fails the secret scan.
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=dest.suffix)
    os.close(tmp_fd)
    tmp_path: Path | None = Path(tmp_name)
    shutil.copy2(source, tmp_path)

    try:
        if scan_secrets.main([str(tmp_path)]) != 0:
            print(
                f"error: secret findings in source; not writing to {dest}",
                file=sys.stderr,
            )
            return 1

        os.replace(tmp_path, dest)
        tmp_path = None
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

    title = args.title or source.stem
    library_log.append(library, "ingest", title, detail=f"sources/{dest_name}", when=now)

    print(f"ingested: {dest}")
    print("next: propose memories/skills with /library:add-memory and /library:add-skill")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
