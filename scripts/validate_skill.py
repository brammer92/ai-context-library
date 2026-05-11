#!/usr/bin/env python3
"""Validate a SKILL.md file against the skill schema.

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
    "id", "name", "version", "description", "status",
    "tags", "agent_scope", "risk_level", "created_at", "updated_at",
]


def validate(path: Path) -> list[str]:
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

    sid = meta.get("id", "")
    if isinstance(sid, str) and sid:
        if not sid.startswith("skill_"):
            errors.append(f"id: must start with 'skill_' (got {sid!r})")
        elif not common.is_snake_case(sid):
            errors.append(f"id: must be lowercase snake_case (got {sid!r})")

    name = meta.get("name", "")
    if not isinstance(name, str) or not name.strip():
        errors.append("name: must be a non-empty string")

    version = meta.get("version", "")
    if version and not common.is_semver(str(version)):
        errors.append(f"version: must be semver (e.g. 1.0.0), got {version!r}")

    description = meta.get("description", "")
    if not isinstance(description, str) or not description.strip():
        errors.append("description: must be a non-empty string")

    status = meta.get("status", "")
    if status and status not in common.SKILL_STATUSES:
        allowed = ", ".join(sorted(common.SKILL_STATUSES))
        errors.append(f"status: {status!r} not in allowed values: {allowed}")

    tags = meta.get("tags")
    if tags is not None:
        if not isinstance(tags, list):
            errors.append("tags: must be a list")
        else:
            for tag in tags:
                if not isinstance(tag, str) or not common.is_kebab_case(tag):
                    errors.append(f"tags: every tag must be kebab-case (got {tag!r})")
                    break

    agent_scope = meta.get("agent_scope")
    if agent_scope is not None:
        if not isinstance(agent_scope, list) or not agent_scope:
            errors.append("agent_scope: must be a non-empty list")
        else:
            for item in agent_scope:
                if not isinstance(item, str) or not item:
                    errors.append(f"agent_scope: non-empty string entries required (got {item!r})")
                    break

    risk = meta.get("risk_level", "")
    if risk and risk not in common.RISK_LEVELS:
        allowed = ", ".join(sorted(common.RISK_LEVELS))
        errors.append(f"risk_level: {risk!r} not in allowed values: {allowed}")

    for ts_key in ("created_at", "updated_at"):
        ts_val = meta.get(ts_key, "")
        if ts_val and not common.is_iso8601(str(ts_val)):
            errors.append(f"{ts_key}: must be ISO-8601 (got {ts_val!r})")

    if not body.strip():
        errors.append("instructions: body is empty")

    for section in common.SKILL_REQUIRED_SECTIONS:
        if section not in body:
            errors.append(f"instructions: missing required section heading {section!r}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a SKILL.md file.")
    parser.add_argument("path", help="Path to the SKILL.md file.")
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
