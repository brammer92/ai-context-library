---
description: Promote an archived memory into the bounded MEMORY.md working set. Refuses if the result would exceed the cap.
argument-hint: <mem_id> [section="Current focus"]
allowed-tools: Bash, Read
---

# /library:promote

## Purpose

Move a memory from the archive (`memories/...`) into `MEMORY.md`, the
bounded working set. Hermes pillar 4 (memory): the working set is
deliberately small; promotion is the explicit gesture that says "this is
worth keeping in front of every agent's eyes right now."

## Usage

```
/library:promote mem_20260511_docker_security_preference
/library:promote mem_20260511_docker_security_preference --section "Open questions"
```

## Behavior

1. Find the memory by id under `memories/...`.
2. Read its title and first non-heading line as a summary.
3. Append a new section under the requested heading inside `MEMORY.md`,
   linking back to the source memory.
4. Check the resulting body against the 2200-character cap.
5. If over cap → refuse, suggest `/library:consolidate` (or pruning).
6. Write `MEMORY.md`, validate via `validate_bounded`, append a log entry.

## Safety Rules

- Refuse if MEMORY.md would exceed the cap.
- Refuse if the memory id can't be found.
- Refuse if `MEMORY.md` is missing — direct the user to `/library:init`.
- Never delete the source memory. Promotion copies a reference.

## Expected Output

A confirmation with the new MEMORY.md size relative to the cap (e.g.
`promoted mem_xxx to MEMORY.md (now 412/2200 chars)`) and the suggested
next command (`/library:review` then `/library:commit`).

## Implementation

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/library_promote.py" \
    --mem-id "$ARGUMENTS" \
    --library "${AI_CONTEXT_LIBRARY_PATH:-$PWD}"
```

If the user supplied a `--section` argument, pass it through.

## Safety Reminder

Never auto-commit. Never auto-push. Never overwrite without explicit
approval.
