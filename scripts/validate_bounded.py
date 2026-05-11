#!/usr/bin/env python3
"""Validate one of the Hermes harness bounded files: MEMORY.md, USER.md,
or CONSTRAINTS.md.

Rules:
    - File starts with YAML frontmatter (delimited by '---').
    - Frontmatter has `updated_at` (ISO-8601) and `cap` (int matching the
      registered cap for the file).
    - Markdown body length is at most the registered cap.

Exit codes:
    0  valid
    1  invalid (errors printed to stderr)
    2  bad invocation (e.g. file is not a registered bounded file)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import common


REQUIRED_KEYS = ["updated_at", "cap"]


def validate(path: Path) -> list[str]:
    errors: list[str] = []

    if not path.exists():
        return [f"file does not exist: {path}"]
    if not path.is_file():
        return [f"not a regular file: {path}"]
    if path.name not in common.HERMES_CAPS:
        return [
            f"{path.name}: not a registered bounded file "
            f"(expected one of {sorted(common.HERMES_CAPS)})"
        ]

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

    ts = meta.get("updated_at", "")
    if ts and not common.is_iso8601(str(ts)):
        errors.append(f"updated_at: must be ISO-8601 (got {ts!r})")

    declared_cap = meta.get("cap")
    registered_cap = common.HERMES_CAPS[path.name]
    if declared_cap is not None and declared_cap != registered_cap:
        errors.append(
            f"cap: declared cap ({declared_cap}) does not match registered "
            f"cap for {path.name} ({registered_cap})"
        )

    body_len = len(body)
    if body_len > registered_cap:
        errors.append(
            f"body: {body_len} chars exceeds cap {registered_cap} "
            f"(over by {body_len - registered_cap}); consolidate or move "
            f"content into memories/"
        )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Hermes-bounded file.")
    parser.add_argument("path", help="Path to MEMORY.md, USER.md, or CONSTRAINTS.md.")
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
