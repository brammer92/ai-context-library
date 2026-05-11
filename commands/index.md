---
description: Regenerate index.md — the auto-maintained content catalog. The PostToolUse hook runs this automatically; the command is the manual fallback.
allowed-tools: Bash, Read
---

# /library:index

## Purpose

Regenerate `<library>/index.md` from the current state of the library.
This is **Karpathy LLM Wiki's content catalog** — one line per page,
grouped by section, so any agent (Claude Code, Claude web, ChatGPT) can
locate content without scanning every folder.

The `PostToolUse` hook calls this script automatically after any write
under the library subtree. The manual command is the fallback when you
want a fresh index without writing.

## Usage

```
/library:index
```

## Behavior

1. Resolve the library root.
2. Walk `MEMORY.md`, `USER.md`, `CONSTRAINTS.md`, `memories/**`,
   `skills/*/SKILL.md`, `context/*.md`, `sources/*`, `projects/*`, and
   `prompts/*.md`.
3. Extract title and short summary for each entry.
4. Write a deterministic `index.md` grouped by section.

## Safety Rules

- Read-only on every file except `index.md` itself.
- Idempotent: regenerating with no library changes produces byte-identical
  output.

## Expected Output

A single line: `regenerated: /path/to/index.md`.

## Implementation

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/library_index.py" "${AI_CONTEXT_LIBRARY_PATH:-$PWD}"
```

## Safety Reminder

This command is read-only with respect to user content. Never auto-commit
the regenerated index — the commit step is `/library:commit`.
