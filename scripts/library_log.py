#!/usr/bin/env python3
"""Append-only log writer for the AI context library's log.md.

Format: each entry begins with `## [YYYY-MM-DD HH:MM:SSZ] <operation> | <subject>`
followed by an optional indented detail block. Newest entries appear at the
top of the file. The Python API never truncates existing entries — it reads
the file, prepends the new entry, and writes back.

Usage:
    python scripts/library_log.py --operation ingest \
        --subject "Hermes article" [--detail "..."] [--library /path]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import common


LOG_HEADER = (
    "# log\n\n"
    "Append-only chronological record of library operations. Newest entries\n"
    "at the top. Format: `## [YYYY-MM-DD HH:MM:SSZ] <operation> | <subject>`.\n\n"
)


def _now_log_ts(when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_entry(ts: str, operation: str, subject: str, detail: str | None) -> str:
    body = f"## [{ts}] {operation} | {subject}\n"
    if detail:
        for line in detail.strip().splitlines():
            body += f"    {line}\n"
    return body


def append(
    library: Path,
    operation: str,
    subject: str,
    *,
    detail: str | None = None,
    when: datetime | None = None,
) -> Path:
    """Prepend a new entry to <library>/log.md. Returns the log path.

    Raises ValueError if `library / "log.md"` would escape the allowed
    library subtree.
    """
    log_path = library / "log.md"
    if not common.is_under_allowed_library_path(Path("log.md")):
        raise ValueError("log.md is not an allowed library root file")
    ts = _now_log_ts(when)
    new_entry = _format_entry(ts, operation, subject, detail)

    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        # Find the first heading-2 entry; insert the new entry before it.
        # If there are no entries yet, append to the header.
        marker = "\n## ["
        idx = existing.find(marker)
        if idx == -1:
            # No prior entries. Append after whatever header is present.
            if not existing.endswith("\n"):
                existing += "\n"
            new_text = existing + new_entry
        else:
            new_text = existing[: idx + 1] + new_entry + existing[idx + 1 :]
    else:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        new_text = LOG_HEADER + new_entry

    log_path.write_text(new_text, encoding="utf-8")
    return log_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append an entry to <library>/log.md.")
    parser.add_argument("--operation", required=True, help="Operation name (e.g. ingest, write, lint).")
    parser.add_argument("--subject", required=True, help="One-line subject of the entry.")
    parser.add_argument("--detail", default=None, help="Optional multi-line detail block.")
    parser.add_argument("--library", default=None, help="Library root (defaults to $AI_CONTEXT_LIBRARY_PATH or cwd).")
    args = parser.parse_args(argv)

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    path = append(library, args.operation, args.subject, detail=args.detail)
    print(f"appended: {path}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
