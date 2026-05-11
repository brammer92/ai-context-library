---
description: Create a reusable skill folder (SKILL.md + examples + validation) from the user's input.
argument-hint: <skill description>
allowed-tools: Bash, Read
---

# /library:add-skill

## Purpose

Create a new reusable skill in the AI context library. Generates a folder
under `skills/<slug>/` containing `SKILL.md`, `examples.md`, and
`validation.md`. **Does not commit.**

## Usage

```
/library:add-skill Create a skill for reviewing Docker Compose files for security issues.
```

## Behavior

1. Extract `--name` (human-readable) and `--description` (one sentence)
   from `$ARGUMENTS`. If either is unclear, ask the user.
2. Infer `--tags` from the description (kebab-case).
3. Choose `--risk-level` based on potential blast radius (default `medium`).
4. Call `create_skill.py`.
5. Show the generated folder path and the three files inside.
6. Show the resulting `git diff`.
7. Tell the user the skill is not committed and suggest `/library:review`.

## Safety Rules

- Reject skills that recommend unsafe defaults (e.g. mounting
  `/var/run/docker.sock` without authentication). If the request implies
  one, warn the user explicitly before creating.
- Refuse to overwrite an existing skill folder.
- Refuse to commit any secrets surfaced by the scan.
- Never commit.

## Expected Output

A confirmation listing the new files, the suggested next command, and a
short summary of the inferred tags and risk level.

## Implementation

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/create_skill.py" \
  --name "<inferred name>" \
  --description "<inferred one-sentence description>" \
  --tags "<inferred,comma,separated>" \
  --risk-level "<low|medium|high>" \
  --library "${AI_CONTEXT_LIBRARY_PATH:-$PWD}"
```

Pass `--dry-run` first if the user asks to preview.

## Safety Reminder

Never auto-commit. Never auto-push. Never overwrite without explicit approval.
