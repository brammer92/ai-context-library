---
description: Show a status report for the AI context library — branch, pending changes, counts, validation, and secret-scan summary.
allowed-tools: Bash, Read
---

# /library:status

## Purpose

Show a comprehensive status report for the AI context library, including
git state, validation results, secret-scan findings, and a recommended next
action.

## Usage

```
/library:status
```

## Behavior

1. Resolve the library root from `$AI_CONTEXT_LIBRARY_PATH` (defaults to
   the current working directory).
2. Print:
   - Library path
   - Git branch and sanitized origin URL (no userinfo)
   - Last commit (oneline)
   - Pending changes (count + up to 20 paths)
   - Memory count
   - Skill count
   - Validation summary (`N/M valid`)
   - Secret-scan finding count
   - Recommended next action

## Safety Rules

- Read-only. Does not modify any file.
- Strips userinfo from any remote URL before displaying.

## Expected Output

A plain-text status block ending with a one-line recommendation: `CLEAN`,
`READY`, or `FIX`.

## Implementation

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/library_status.py" "${AI_CONTEXT_LIBRARY_PATH:-$PWD}"
```

## Safety Reminder

This command is read-only. Never auto-commit. Never auto-push.
