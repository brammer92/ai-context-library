#!/usr/bin/env python3
"""Validate a memory Markdown file against the memory schema.

Exit codes:
    0  valid
    1  invalid (errors printed to stderr)
    2  bad invocation
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import common


REQUIRED_KEYS = [
    "id", "title", "type", "scope", "agent_scope",
    "tags", "importance", "created_at", "updated_at", "source",
]


def validate(path: Path) -> list[str]:
    """Return list of error strings; empty list means valid."""
    errors: list[str] = []

    if not path.exists():
        return [f"file does not exist: {path}"]
    if not path.is_file():
        return [f"not a regular file: {path}"]

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"could not read file: {exc}"]

    try:
        meta, body = common.parse_frontmatter(text)
    except ValueError as exc:
        return [f"frontmatter: {exc}"]
    if not meta:
        return ["frontmatter: missing or empty (file must start with '---')"]

    for key in REQUIRED_KEYS:
        if key not in meta:
            errors.append(f"{key}: missing required field")

    mid = meta.get("id", "")
    if isinstance(mid, str) and mid:
        if not mid.startswith("mem_"):
            errors.append(f"id: must start with 'mem_' (got {mid!r})")
        elif not common.is_snake_case(mid):
            errors.append(f"id: must be lowercase snake_case (got {mid!r})")

    title = meta.get("title", "")
    if not isinstance(title, str) or not title.strip():
        errors.append("title: must be a non-empty string")

    mtype = meta.get("type", "")
    if mtype and mtype not in common.MEMORY_TYPES:
        allowed = ", ".join(sorted(common.MEMORY_TYPES))
        errors.append(f"type: {mtype!r} not in allowed values: {allowed}")

    scope = meta.get("scope", "")
    if scope and scope not in common.MEMORY_SCOPES:
        allowed = ", ".join(sorted(common.MEMORY_SCOPES))
        errors.append(f"scope: {scope!r} not in allowed values: {allowed}")

    agent_scope = meta.get("agent_scope")
    if agent_scope is not None:
        if not isinstance(agent_scope, list) or not agent_scope:
            errors.append("agent_scope: must be a non-empty list")
        else:
            for item in agent_scope:
                if not isinstance(item, str) or not item:
                    errors.append(f"agent_scope: non-empty string entries required (got {item!r})")
                    break

    tags = meta.get("tags")
    if tags is not None:
        if not isinstance(tags, list):
            errors.append("tags: must be a list")
        else:
            for tag in tags:
                if not isinstance(tag, str) or not common.is_kebab_case(tag):
                    errors.append(f"tags: every tag must be kebab-case (got {tag!r})")
                    break

    importance = meta.get("importance", "")
    if importance and importance not in common.IMPORTANCE_VALUES:
        allowed = ", ".join(sorted(common.IMPORTANCE_VALUES))
        errors.append(f"importance: {importance!r} not in allowed values: {allowed}")

    for ts_key in ("created_at", "updated_at"):
        ts_val = meta.get(ts_key, "")
        if ts_val and not common.is_iso8601(str(ts_val)):
            errors.append(f"{ts_key}: must be ISO-8601 (got {ts_val!r})")

    source = meta.get("source", "")
    if source is not None and (not isinstance(source, str) or not source.strip()):
        errors.append("source: must be a non-empty string")

    # Body content (canonical 'content' field).
    if not body.strip():
        errors.append("content: body is empty")
    else:
        ok, reason = common.useful_content_heuristic(body)
        if not ok:
            errors.append(f"content: {reason}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a memory Markdown file.")
    parser.add_argument("path", help="Path to the memory .md file.")
    args = parser.parse_args(argv)

    target = Path(args.path).expanduser().resolve()
    errors = validate(target)
    if errors:
        print(f"INVALID: {target}", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"OK: {target}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
