#!/usr/bin/env python3
"""Generate a reusable skill folder under <library>/skills/<slug>/.

Produces SKILL.md, examples.md, and validation.md. Validates the resulting
SKILL.md and runs the secret scanner on the new folder.

Exit codes:
    0  success
    1  validation or secret-scan failure (folder removed)
    2  bad invocation
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import common
import scan_secrets
import validate_skill


SKILL_MD_TEMPLATE = """---
id: {id}
name: {name}
version: {version}
description: {description_yaml}
status: {status}
tags:
{tags_block}
agent_scope:
{agent_scope_block}
risk_level: {risk_level}
created_at: "{created_at}"
updated_at: "{updated_at}"
---

# {name}

## Purpose

{description}

## When To Use

Use this skill when the situation matches its intended scope. Replace this
paragraph with concrete triggers (file types, request patterns, environments).

## Inputs Expected

- Replace with the concrete inputs this skill needs.
- Document optional inputs separately.

## Procedure

1. Replace with the first concrete step.
2. Replace with the second concrete step.
3. Continue as needed.

## Output Format

Describe the structure of the output (summary, sections, code blocks, etc.).

## Safety Checks

- Replace with safety rules specific to this skill.
- Reject inputs that would violate the rules.

## Failure Modes

- Replace with known failure modes and how to surface them.
"""

EXAMPLES_MD_TEMPLATE = """# Examples — {name}

## Example 1: Typical input

Describe a representative input.

```
<paste a realistic input here>
```

### Expected output

```
<paste the structured output the skill should produce>
```

## Example 2: Edge case

Describe a non-trivial edge case the skill must handle.
"""

VALIDATION_MD_TEMPLATE = """# Validation — {name}

Run the following checks before publishing this skill.

- [ ] Confirm every Procedure step has been exercised on a real input.
- [ ] Confirm Safety Checks block known-bad inputs.
- [ ] Confirm Output Format matches consumer expectations.
- [ ] Re-run `python scripts/validate_skill.py path/to/SKILL.md`.
- [ ] Re-run `python scripts/scan_secrets.py path/to/skill_folder/`.
"""


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _block_list(items: list[str], indent: str = "  ") -> str:
    if not items:
        return f'{indent}- "*"'
    return "\n".join(f'{indent}- {_quote_if_needed(item)}' for item in items)


def _quote_if_needed(s: str) -> str:
    if s == "*" or any(c in s for c in [":", "#", '"', "'"]):
        return f'"{s}"'
    return s


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a reusable skill folder.")
    parser.add_argument("--name", required=True, help="Human-readable skill name.")
    parser.add_argument("--description", required=True, help="One-sentence description.")
    parser.add_argument("--tags", default="", help="Comma-separated kebab-case tags.")
    parser.add_argument("--risk-level", default="medium", choices=sorted(common.RISK_LEVELS))
    parser.add_argument("--status", default="active", choices=sorted(common.SKILL_STATUSES))
    parser.add_argument("--version", default="1.0.0", help="Semantic version.")
    parser.add_argument("--agent-scope", default=None, help="Comma-separated. Defaults to '*' or $AI_CONTEXT_LIBRARY_DEFAULT_AGENT_SCOPE.")
    parser.add_argument("--library", default=None, help="Library root. Defaults to $AI_CONTEXT_LIBRARY_PATH or cwd.")
    parser.add_argument("--force", action="store_true", help="Overwrite if target folder exists.")
    parser.add_argument("--dry-run", action="store_true", help="Print would-be content and exit.")
    args = parser.parse_args(argv)

    tags = _split_csv(args.tags)
    agent_scope = _split_csv(args.agent_scope or os.environ.get("AI_CONTEXT_LIBRARY_DEFAULT_AGENT_SCOPE") or "*") or ["*"]

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not common.is_semver(args.version):
        print(f"error: --version must be semver (got {args.version!r})", file=sys.stderr)
        return 2

    slug = common.slugify(args.name)
    if not slug:
        print("error: could not derive slug from --name", file=sys.stderr)
        return 2
    sid = common.generate_skill_id(args.name)
    now = common.now_iso()

    description_yaml = args.description.replace('"', '\\"')
    if any(c in args.description for c in [":", "#"]):
        description_yaml = f'"{description_yaml}"'

    skill_md = SKILL_MD_TEMPLATE.format(
        id=sid,
        name=args.name,
        version=args.version,
        description=args.description,
        description_yaml=description_yaml,
        status=args.status,
        tags_block=_block_list(tags) if tags else '  - misc',
        agent_scope_block=_block_list(agent_scope),
        risk_level=args.risk_level,
        created_at=now,
        updated_at=now,
    )
    examples_md = EXAMPLES_MD_TEMPLATE.format(name=args.name)
    validation_md = VALIDATION_MD_TEMPLATE.format(name=args.name)

    if args.dry_run:
        target_dir = library / "skills" / slug
        print(f"# would create: {target_dir}/SKILL.md\n")
        print(skill_md)
        print(f"\n# would create: {target_dir}/examples.md\n")
        print(examples_md)
        print(f"\n# would create: {target_dir}/validation.md\n")
        print(validation_md)
        return 0

    target_dir = library / "skills" / slug
    if target_dir.exists() and not args.force:
        print(f"error: refusing to overwrite existing skill folder: {target_dir}", file=sys.stderr)
        return 1
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (target_dir / "examples.md").write_text(examples_md, encoding="utf-8")
    (target_dir / "validation.md").write_text(validation_md, encoding="utf-8")

    skill_path = target_dir / "SKILL.md"
    errors = validate_skill.validate(skill_path)
    if errors:
        print(f"INVALID generated skill at {skill_path}:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        shutil.rmtree(target_dir, ignore_errors=True)
        return 1

    if scan_secrets.main([str(target_dir)]) != 0:
        print(
            f"error: secret findings in generated skill; removing {target_dir}",
            file=sys.stderr,
        )
        shutil.rmtree(target_dir, ignore_errors=True)
        return 1

    print(f"created: {target_dir}/")
    print(f"  - SKILL.md\n  - examples.md\n  - validation.md")
    print("next: review changes with /library:review, then commit with /library:commit")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
