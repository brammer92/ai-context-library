#!/usr/bin/env python3
"""Create the canonical AI context library folder structure.

Behavior:
    - Create missing directories.
    - Create starter files only if absent. Never overwrite existing files.
    - Copy schemas and templates from the plugin's bundled copies.
    - Print every created path and every skipped (already-existing) path.

Usage:
    python scripts/init_library.py [<library_path>]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import common


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_SCHEMAS = PLUGIN_ROOT / "schemas"
PLUGIN_TEMPLATES = PLUGIN_ROOT / "templates"


CANONICAL_DIRS = [
    "context",
    "memories/user",
    "memories/agents",
    "memories/projects",
    "memories/decisions",
    "memories/workflows",
    "memories/security",
    "memories/troubleshooting",
    "skills",
    "projects",
    "prompts",
    "templates",
    "schemas",
    # Karpathy Layer 1 — raw immutable sources.
    "sources",
    # Embeddings layer — canonical vector sidecar for Claude Code's
    # dedup / contradiction / cluster paths.
    "embeddings",
]


README_BODY = """# AI Context Hub

This is your private AI context library. It is the source of truth for
memories, reusable skills, and durable context shared across Claude Code,
Claude web UI, and ChatGPT.

Top-level files:

- `CLAUDE.md` — instructions for Claude Code.
- `AGENTS.md` — generic guidance for any AI agent.
- `CHATGPT.md` — instructions for ChatGPT.

Folders:

- `context/` — durable principles (working style, coding standards, etc.).
- `memories/` — structured memory entries.
- `skills/` — reusable skill folders.
- `projects/` — per-project notes and decisions.
- `prompts/` — reusable prompts.
- `templates/` — file templates for new entries.
- `schemas/` — JSON Schemas for memories and skills.

Use the `library` Claude Code plugin to add, validate, and review entries.
Never commit secrets. Never commit `.env` files.
"""

CLAUDE_MD_BODY = """# CLAUDE.md

Use this AI context library as the source of truth. This library follows
the Hermes 5-pillar harness — the LLM is replaceable; the harness is the
asset.

## The 5 pillars

1. **Instructions** — `CLAUDE.md`, `AGENTS.md`, and `context/*.md` tell you
   how to behave. Re-read them after every few tool calls.
2. **Constraints** — `CONSTRAINTS.md` lists hard guardrails. Never violate
   them, even if a user requests it.
3. **Feedback** — After ~5 tool calls or at the end of a task, retrospect:
   what was saved, what worked, what failed. Run `/library:reflect` when
   you want a structured retrospective.
4. **Memory** — Two-tier:
   - **Working set** (bounded): `MEMORY.md` (≤2200 chars) for current
     focus, `USER.md` (≤1375 chars) for stable preferences. Small caps are
     deliberate — they force consolidation.
   - **Archive**: `memories/**/*.md` is the indexed, validated store. Read
     it for historical context.
5. **Orchestration** — `skills/` holds reusable procedures. When you
   detect a repeating pattern (5+ similar tasks), propose a skill via
   `/library:add-skill`. Run `/library:detect-patterns` to surface
   candidates.

## Workflow

- Read `MEMORY.md`, `USER.md`, and `CONSTRAINTS.md` first — they are tiny.
- Then check `AGENTS.md` and the relevant `context/*.md`.
- For domain-specific context, search `memories/`.
- For repeatable procedures, use `skills/`.
- When durable context is discovered, propose `/library:add-memory`.
  When a procedure repeats, propose `/library:add-skill`. Do not silently
  save. Do not save secrets.
- When working-set files grow stale, propose `/library:consolidate` to
  archive low-value entries into `memories/`.
"""

AGENTS_MD_BODY = """# AGENTS.md

Generic harness contract for any AI agent reading this library. The
contract is structured around the Hermes 5 pillars — instructions,
constraints, feedback, memory, orchestration.

## Instructions (this file)

- Treat this repository as the source of truth for shared context.
- Read agent-specific instructions first: `CLAUDE.md` (Claude Code,
  Claude web UI) or `CHATGPT.md` (ChatGPT). Fall back to this file for
  generic guidance.
- Propose updates rather than writing them silently.

## Constraints (`CONSTRAINTS.md`)

- Always read `CONSTRAINTS.md` before suggesting destructive operations.
- Never include secrets in any file. Never recommend committing `.env`
  files or PEM blocks.
- Never bypass the validation/commit gates documented in the library
  plugin README.

## Feedback (retrospection)

- After ~5 tool calls or at the end of a task, retrospect:
  what just happened, what worked, what failed, what should be saved.
- If a pattern repeats, propose extracting a skill.
- Run `/library:reflect` for a structured retrospective when available.

## Memory (two-tier)

- **Working set** at the library root: `MEMORY.md` (cap ≤2200 chars) for
  current focus, `USER.md` (cap ≤1375 chars) for stable preferences. The
  caps are deliberate — over the cap, consolidate.
- **Archive** under `memories/<category>/`: indexed, validated entries
  with full YAML frontmatter. This is the long-term store.

## Orchestration (skills + hand-off)

- Reusable procedures live in `skills/<slug>/SKILL.md`.
- When a procedure repeats 5+ times across sessions, propose a skill.
- Skills should self-improve: update `version` and `validation.md` when
  observed failure modes change.
- Hand-off between agents happens through this repo. Anything not in the
  repo is invisible to peer agents.

## Universal rules

- Prefer durable, reusable content over transcript fragments.
- Default to the smallest change that achieves the goal.
- When in doubt, ask the user instead of guessing.
"""

CHATGPT_MD_BODY = """# CHATGPT.md

When using this repository with the ChatGPT GitHub connector, follow the
Hermes 5-pillar harness.

## Read order

1. `MEMORY.md` — current focus, ≤2200 chars.
2. `USER.md` — stable preferences, ≤1375 chars.
3. `CONSTRAINTS.md` — hard guardrails.
4. `AGENTS.md` — generic harness contract.
5. `context/*.md` — domain principles.
6. `memories/**/*.md` — historical context (search by tag).
7. `skills/<slug>/SKILL.md` — reusable procedures.

## Writing back

ChatGPT cannot commit through the connector. To add memories or skills,
use Claude Code with the `library` plugin:

- `/library:add-memory "<durable statement>"`
- `/library:add-skill "<reusable procedure>"`

ChatGPT proposes the content; the user (in Claude Code) reviews, validates,
and commits.

## Hand-off etiquette

- Do not save chat transcripts here.
- Do not save secrets.
- Surface candidate memories / skills back to the user with the suggested
  slash command pre-filled.
"""

CONSTRAINTS_MD_BODY = """---
updated_at: "2026-05-11T00:00:00Z"
cap: 4000
---

# CONSTRAINTS

Hard guardrails for every agent reading this library. Apply unconditionally.
Cap: 4000 characters.

## Never

- Never write secrets, API keys, tokens, passwords, or `.env` contents.
- Never push to GitHub automatically.
- Never run destructive git commands (`reset --hard`, `clean -fd`,
  `push --force`, `filter-branch`, `gc --prune=now`, `rebase`,
  `checkout -- .`).
- Never overwrite an existing memory or skill without explicit user
  approval.
- Never store raw chat transcripts as memories.
- Never recommend mounting `/var/run/docker.sock` directly without
  documented justification.

## Always

- Always validate before committing (`/library:review`).
- Always scan for secrets before writing.
- Always ask the user when intent is ambiguous.
- Always prefer the smallest durable statement over a paragraph.

## Replace this section

Add project-specific or user-specific constraints below this line. Keep
the file under 4000 characters; over the cap, consolidate.
"""

MEMORY_MD_BODY = """---
updated_at: "2026-05-11T00:00:00Z"
cap: 2200
---

# MEMORY

Bounded working-set memory. Cap: 2200 characters. Over the cap,
consolidate older entries into `memories/` via `/library:consolidate`.

## Current focus

(Nothing yet. Add the 1–3 things you are actively working on.)

## Recent decisions

(Nothing yet. Add the most recent decisions worth keeping in working set.)

## Open questions

(Nothing yet. Add open questions you want every agent to see at session
start.)
"""

USER_MD_BODY = """---
updated_at: "2026-05-11T00:00:00Z"
cap: 1375
---

# USER

Bounded preferences for this user. Cap: 1375 characters. Stable values
only — anything situational goes in `memories/` instead.

## Identity

(Role, primary tools, languages you work in.)

## Working style

(How you collaborate, when to ask vs. act, preferred verbosity.)

## Non-negotiables

(Hard requirements an agent must respect every session.)
"""

INDEX_STARTER_BODY = """<!-- generated by /library:index — do not edit by hand -->
<!-- updated_at: 2026-05-11T00:00:00Z -->

# index

Content catalog for this AI context library. One entry per page, grouped
by section. Auto-maintained by the plugin's PostToolUse hook and the
`/library:index` command.

## Working Set

(empty)

## Memories

(empty)

## Skills

(empty)

## Context

(empty)

## Sources

(empty)

## Projects

(empty)

## Prompts

(empty)
"""

LOG_STARTER_BODY = """# log

Append-only chronological record of library operations. Newest entries at
the top. Format: `## [YYYY-MM-DD HH:MM:SSZ] <operation> | <subject>`.

## [2026-05-11T00:00:00Z] init | library initialized
"""

EMBEDDINGS_README_BODY = """# embeddings/

Canonical vector sidecar for this library's embeddings layer.

## What lives here

- `memories.jsonl` — one JSON line per memory: `id`, `content_hash`,
  `model`, `dim`, `embedded_at`, `type`, `tags`, `vector`. Generated by
  the `library` plugin's `scripts/embed_memory.py` (write-time hook and
  `--backfill`). It is git-tracked and reviewed/committed like any other
  artifact — never auto-committed.

## What this is NOT

This is **Claude Code infrastructure**, not a cross-agent retrieval
store. Claude web and ChatGPT read the raw Markdown via their GitHub
connectors; they cannot run nearest-neighbour search and get no direct
benefit from these vectors. The indirect benefit is a cleaner, dedup'd,
contradiction-checked corpus for all three agents.

## Sync model

`memories.jsonl` is canonical. ClickHouse (`library_embeddings`) is a
rebuildable query cache populated by `scripts/embed_load_clickhouse.py`.
`content_hash` lets consumers detect a stale vector and degrade rather
than return a bad neighbour.
"""

CONTEXT_FILES: dict[str, str] = {
    "context/user-profile.md": "# User Profile\n\nDescribe role, responsibilities, and goals here.\n",
    "context/working-style.md": "# Working Style\n\nDescribe how you like to collaborate with agents here.\n",
    "context/coding-standards.md": "# Coding Standards\n\nDescribe language conventions, formatting rules, and review expectations.\n",
    "context/security-principles.md": "# Security Principles\n\nDescribe security defaults agents should respect.\n",
    "context/infrastructure-preferences.md": "# Infrastructure Preferences\n\nDescribe hosting, deployment, and tooling preferences.\n",
    "context/project-decisions.md": "# Project Decisions\n\nLink to architectural decision records (ADRs) under `projects/`.\n",
    "context/glossary.md": "# Glossary\n\nDefine project-specific terminology here.\n",
}

TEMPLATE_FILES: dict[str, str] = {
    "templates/decision-record.md": (
        "# Decision: <title>\n\n"
        "Date: <YYYY-MM-DD>\n"
        "Status: proposed | accepted | superseded\n\n"
        "## Context\n\n## Decision\n\n## Consequences\n"
    ),
    "templates/project-template.md": (
        "# Project: <name>\n\n"
        "## Overview\n\n## Current State\n\n## Architecture\n\n"
        "## Decisions\n\n## TODO\n"
    ),
}


def _write_if_absent(path: Path, content: str, created: list[Path], skipped: list[Path]) -> None:
    if path.exists():
        skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    created.append(path)


def _copy_if_absent(src: Path, dst: Path, created: list[Path], skipped: list[Path]) -> None:
    if dst.exists():
        skipped.append(dst)
        return
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    created.append(dst)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize an AI context library.")
    parser.add_argument("library", nargs="?", default=None, help="Library root (defaults to $AI_CONTEXT_LIBRARY_PATH or cwd).")
    args = parser.parse_args(argv)

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    created: list[Path] = []
    skipped: list[Path] = []

    # Folders.
    for rel in CANONICAL_DIRS:
        d = library / rel
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(d)
        else:
            skipped.append(d)

    # Top-level files.
    _write_if_absent(library / "README.md", README_BODY, created, skipped)
    _write_if_absent(library / "CLAUDE.md", CLAUDE_MD_BODY, created, skipped)
    _write_if_absent(library / "AGENTS.md", AGENTS_MD_BODY, created, skipped)
    _write_if_absent(library / "CHATGPT.md", CHATGPT_MD_BODY, created, skipped)

    # Hermes harness — bounded "active context" files.
    _write_if_absent(library / "CONSTRAINTS.md", CONSTRAINTS_MD_BODY, created, skipped)
    _write_if_absent(library / "MEMORY.md", MEMORY_MD_BODY, created, skipped)
    _write_if_absent(library / "USER.md", USER_MD_BODY, created, skipped)

    # Karpathy LLM Wiki — auto-maintained index and append-only log.
    _write_if_absent(library / "index.md", INDEX_STARTER_BODY, created, skipped)
    _write_if_absent(library / "log.md", LOG_STARTER_BODY, created, skipped)

    # Context starter files.
    for rel, body in CONTEXT_FILES.items():
        _write_if_absent(library / rel, body, created, skipped)

    # Embeddings layer — explanatory README for the vector sidecar.
    _write_if_absent(library / "embeddings" / "README.md", EMBEDDINGS_README_BODY, created, skipped)

    # Templates (inline).
    for rel, body in TEMPLATE_FILES.items():
        _write_if_absent(library / rel, body, created, skipped)

    # Templates from bundled plugin templates.
    _copy_if_absent(PLUGIN_TEMPLATES / "memory.md", library / "templates" / "memory-entry.md", created, skipped)
    _copy_if_absent(PLUGIN_TEMPLATES / "skill" / "SKILL.md", library / "templates" / "skill-template.md", created, skipped)

    # Schemas (copy from plugin).
    _copy_if_absent(PLUGIN_SCHEMAS / "memory.schema.json", library / "schemas" / "memory.schema.json", created, skipped)
    _copy_if_absent(PLUGIN_SCHEMAS / "skill.schema.json", library / "schemas" / "skill.schema.json", created, skipped)

    print(f"AI Context Library initialized at: {library}")
    print(f"Created: {len(created)}    Skipped (already existed): {len(skipped)}")
    if created:
        print("\nCreated:")
        for p in created:
            print(f"  + {p.relative_to(library) if library in p.parents or p == library else p}")
    if skipped:
        print("\nSkipped:")
        for p in skipped[:20]:
            print(f"  = {p.relative_to(library) if library in p.parents or p == library else p}")
        if len(skipped) > 20:
            print(f"  ... and {len(skipped) - 20} more")
    print("\nNext steps:")
    print(f"  cd {library}")
    print("  git init && git add . && git commit -m 'chore: initialize AI context hub'")
    print("  Add a private GitHub remote and push when ready.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
