#!/usr/bin/env python3
"""Promote an archived memory into MEMORY.md (the bounded working set).

Appends a short reference section to MEMORY.md under a chosen heading.
Refuses if the resulting body would exceed the 2200-character cap.

Usage:
    python scripts/library_promote.py --mem-id mem_xxx \
        [--section "Current focus"] [--library /path] [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import common
import library_log
import validate_bounded


def _find_memory(library: Path, mem_id: str) -> Path | None:
    mem_root = library / "memories"
    if not mem_root.is_dir():
        return None
    for path in mem_root.rglob(f"{mem_id}.md"):
        return path
    # Fallback: scan frontmatter ids.
    for path in mem_root.rglob("*.md"):
        try:
            meta, _ = common.parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if meta.get("id") == mem_id:
            return path
    return None


def _build_promoted_body(
    existing_body: str, section: str, title: str, mem_id: str, rel_link: str, summary: str
) -> str:
    """Append a new entry under `section`. If the section header is missing,
    create it at the bottom."""
    section_header = f"## {section}"
    entry = (
        f"\n### {title} (`{mem_id}`)\n\n"
        f"See [memory]({rel_link}).\n\n"
        f"{summary}\n"
    )

    # Line-anchored match so `## Current` doesn't collide with `## Current focus`.
    header_re = re.compile(
        rf"(?m)^{re.escape(section_header)}[ \t]*$"
    )
    match = header_re.search(existing_body)
    if match is not None:
        # Move past the heading line.
        line_end = existing_body.find("\n", match.end())
        if line_end == -1:
            return existing_body + "\n" + entry
        # Search the remainder for the NEXT `## ` heading. Use a line-anchored
        # regex so an immediately adjacent `## Other` is found even with no
        # leading blank line.
        rest = existing_body[line_end + 1 :]
        next_match = re.search(r"(?m)^## ", rest)
        if next_match is None:
            return existing_body.rstrip("\n") + "\n" + entry
        insert_at = line_end + 1 + next_match.start()
        return existing_body[:insert_at] + entry + existing_body[insert_at:]
    # Section absent — create at end.
    return existing_body.rstrip("\n") + f"\n\n{section_header}\n{entry}"


def promote(
    library: Path,
    mem_id: str,
    *,
    section: str = "Current focus",
    dry_run: bool = False,
    when: datetime | None = None,
) -> tuple[int, str]:
    """Return (exit_code, message)."""
    when = when or datetime.now(timezone.utc)
    mem_path = _find_memory(library, mem_id)
    if mem_path is None:
        return 1, f"memory not found: {mem_id}"

    try:
        text = mem_path.read_text(encoding="utf-8")
        meta, body = common.parse_frontmatter(text)
    except (OSError, ValueError) as exc:
        return 1, f"could not read memory: {exc}"

    title = str(meta.get("title", mem_id))
    # First non-heading, non-empty line of body as summary.
    summary = ""
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        summary = s
        break
    if len(summary) > 200:
        summary = summary[:197] + "..."

    rel_link = mem_path.relative_to(library).as_posix()

    memory_md = library / "MEMORY.md"
    if not memory_md.is_file():
        return 1, "MEMORY.md not found — run /library:init first"
    try:
        existing_full = memory_md.read_text(encoding="utf-8")
        existing_meta, existing_body = common.parse_frontmatter(existing_full)
    except (OSError, ValueError) as exc:
        return 1, f"could not read MEMORY.md: {exc}"

    new_body = _build_promoted_body(existing_body, section, title, mem_id, rel_link, summary)
    cap = common.HERMES_CAPS["MEMORY.md"]
    if len(new_body) > cap:
        return 1, (
            f"refusing to promote: MEMORY.md would be {len(new_body)} chars "
            f"(cap {cap}). Run /library:consolidate first."
        )

    existing_meta["updated_at"] = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    existing_meta.setdefault("cap", cap)

    serialized = common.dump_frontmatter(existing_meta, new_body)

    if dry_run:
        return 0, f"would write MEMORY.md ({len(new_body)}/{cap} chars):\n{serialized}"

    memory_md.write_text(serialized, encoding="utf-8")
    errors = validate_bounded.validate(memory_md)
    if errors:
        # Restore the pre-write content so MEMORY.md isn't left corrupted.
        memory_md.write_text(existing_full, encoding="utf-8")
        return 1, "post-write validation failed (rolled back):\n  - " + "\n  - ".join(errors)

    library_log.append(library, "promote", f"{mem_id} -> MEMORY.md", when=when)
    return 0, f"promoted {mem_id} to MEMORY.md (now {len(new_body)}/{cap} chars)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Promote a memory into MEMORY.md.")
    parser.add_argument("--mem-id", required=True, help="The mem_* id to promote.")
    parser.add_argument("--section", default="Current focus")
    parser.add_argument("--library", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rc, msg = promote(library, args.mem_id, section=args.section, dry_run=args.dry_run)
    print(msg)
    return rc


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
