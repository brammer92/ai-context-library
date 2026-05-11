---
description: Initialize a missing or incomplete AI context library structure at $AI_CONTEXT_LIBRARY_PATH.
allowed-tools: Bash, Read
---

# /library:init

## Purpose

Initialize a missing or incomplete AI context library structure. Safe to run
on an already-populated library — never overwrites existing files.

## Usage

```
/library:init
```

## Behavior

1. Detect the library root from `$AI_CONTEXT_LIBRARY_PATH` (falling back to
   the current working directory).
2. Create any missing canonical directories (`context/`, `memories/...`,
   `skills/`, `projects/`, `prompts/`, `templates/`, `schemas/`).
3. Create starter `README.md`, `CLAUDE.md`, `AGENTS.md`, `CHATGPT.md`, and
   `context/*.md` files only if absent.
4. Copy the bundled JSON schemas and templates if not already present.
5. Print every created path and every skipped (already-present) path.

## Safety Rules

- Never overwrite existing files.
- Never write inside `.git/`, `node_modules/`, `.venv/`, or any disallowed path.

## Expected Output

A summary listing created and skipped paths, plus next-step instructions
(`git init`, `git remote add origin ...`, and a manual first push).

## Implementation

Invoke the bundled initializer:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init_library.py" "${AI_CONTEXT_LIBRARY_PATH:-$PWD}"
```

After running, show the user the created/skipped summary verbatim. Do not
proceed to `git init` automatically — the user runs it manually.

## Safety Reminder

Never auto-commit. Never auto-push. Never overwrite without explicit approval.
