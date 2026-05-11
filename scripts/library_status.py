#!/usr/bin/env python3
"""Print a status report for the AI context library.

Sections:
    - Library path
    - Git branch + sanitized remote
    - Last commit oneline
    - Pending changes
    - Memory count
    - Skill count
    - Validation summary
    - Secret scan summary
    - Recommended next action
"""
from __future__ import annotations

import argparse
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import common
import git_helpers
import scan_secrets
import validate_memory
import validate_skill


def _count_memories(library: Path) -> int:
    folder = library / "memories"
    if not folder.is_dir():
        return 0
    return sum(1 for _ in folder.rglob("*.md"))


def _count_skills(library: Path) -> int:
    folder = library / "skills"
    if not folder.is_dir():
        return 0
    return sum(1 for sub in folder.iterdir() if sub.is_dir() and (sub / "SKILL.md").is_file())


def _validate_all(library: Path) -> tuple[int, int, list[str]]:
    """Return (valid_count, total_count, failures)."""
    failures: list[str] = []
    total = 0
    valid = 0

    mem_root = library / "memories"
    if mem_root.is_dir():
        for path in mem_root.rglob("*.md"):
            total += 1
            errors = validate_memory.validate(path)
            if errors:
                failures.append(f"{path}: memory invalid ({len(errors)} error(s))")
            else:
                valid += 1

    skill_root = library / "skills"
    if skill_root.is_dir():
        for sub in skill_root.iterdir():
            if not sub.is_dir():
                continue
            skill_md = sub / "SKILL.md"
            if not skill_md.is_file():
                continue
            total += 1
            errors = validate_skill.validate(skill_md)
            if errors:
                failures.append(f"{skill_md}: skill invalid ({len(errors)} error(s))")
            else:
                valid += 1

    return valid, total, failures


def _scan_library(library: Path) -> int:
    """Return secret finding count without printing each one to stdout."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        scan_secrets.main([str(library)])
    findings = 0
    for line in buf.getvalue().splitlines():
        if line.startswith("Secret scan:"):
            parts = line.split()
            try:
                findings = int(parts[2])
            except (IndexError, ValueError):
                findings = 0
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show AI context library status.")
    parser.add_argument("library", nargs="?", default=None, help="Library root (defaults to $AI_CONTEXT_LIBRARY_PATH or cwd).")
    args = parser.parse_args(argv)

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print("AI Context Library — status")
    print("=" * 40)
    print(f"Path:       {library}")

    if git_helpers.is_git_repo(library):
        print(f"Branch:     {git_helpers.git_branch(library) or '(detached HEAD)'}")
        print(f"Remote:     {git_helpers.git_remote_sanitized(library) or '(no origin)'}")
        print(f"Last commit: {git_helpers.git_log_one(library) or '(no commits yet)'}")
        pending = git_helpers.git_status_short(library)
        if pending:
            print(f"Pending changes: {len(pending)}")
            for status, path in pending[:20]:
                print(f"  {status} {path}")
            if len(pending) > 20:
                print(f"  ... and {len(pending) - 20} more")
        else:
            print("Pending changes: 0")
    else:
        print("Git:        not a git repository")
        pending = []

    mem_count = _count_memories(library)
    skill_count = _count_skills(library)
    print(f"Memories:   {mem_count}")
    print(f"Skills:     {skill_count}")

    # Hermes harness working set: cap pressure on bounded files.
    over_cap_count = 0
    cap_lines: list[str] = []
    for name, cap in common.HERMES_CAPS.items():
        p = library / name
        if p.is_file():
            try:
                body_len = common.body_char_count(p.read_text(encoding="utf-8"))
            except OSError:
                continue
            pct = (body_len / cap) * 100
            cap_lines.append(f"  {name}: {body_len}/{cap} chars ({pct:.0f}%)")
            if body_len > cap:
                over_cap_count += 1
        else:
            cap_lines.append(f"  {name}: (not present)")
    print("Working set:")
    for line in cap_lines:
        print(line)

    # Karpathy LLM Wiki indicators.
    src_root = library / "sources"
    source_count = sum(1 for _ in src_root.iterdir() if _.is_file()) if src_root.is_dir() else 0
    log_path = library / "log.md"
    log_entries = 0
    if log_path.is_file():
        try:
            log_entries = sum(
                1 for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.startswith("## [")
            )
        except OSError:
            log_entries = 0
    print(f"Sources:    {source_count}")
    print(f"Log:        {log_entries} entries")

    valid, total, failures = _validate_all(library)
    print(f"Validation: {valid}/{total} valid")
    for fail in failures[:10]:
        print(f"  - {fail}")
    if len(failures) > 10:
        print(f"  ... and {len(failures) - 10} more")

    findings = _scan_library(library)
    print(f"Secret scan: {findings} finding(s)")

    print()
    print("Recommended next action:")
    if findings > 0:
        print("  FIX: review and remove secrets before any commit")
    elif failures:
        print("  FIX: run /library:review for details")
    elif over_cap_count:
        print("  FIX: bounded file(s) over cap — run /library:consolidate")
    elif pending:
        print("  READY: run /library:review then /library:commit")
    else:
        print("  CLEAN: nothing to do")

    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
