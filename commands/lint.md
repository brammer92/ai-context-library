---
description: Lint the AI context library — schema integrity, stale claims, orphan memories, cross-reference gaps, cap pressure, tag distribution, and recent activity.
allowed-tools: Bash, Read
---

# /library:lint

## Purpose

Periodic health check for the context library. Merged Karpathy "lint"
operation (contradictions, stale claims, orphans, missing cross-references)
with Hermes pillar 3 (feedback) retrospective (cap pressure on bounded
files, tag distribution, recent activity, actionable recommendations).

## Usage

```
/library:lint
/library:lint --stale-days 60 --recent-days 14
```

## Behavior

1. Resolve the library root.
2. Run every memory through `validate_memory`, every skill through
   `validate_skill`, and every bounded file through `validate_bounded`.
3. Identify memories whose `updated_at` is older than `--stale-days`
   (default 90).
4. Identify memory ids never referenced by any other file (orphans).
5. Identify cross-reference gaps: skill bodies mentioning a `mem_*` id
   where the memory doesn't reference the skill back.
6. Report cap pressure on `MEMORY.md`, `USER.md`, `CONSTRAINTS.md` (≥80%
   warning, ≥95% finding).
7. Compute top 10 tags by memory count.
8. List memories created within the last `--recent-days` (default 7).
9. Produce a list of actionable recommendations.

## Safety Rules

- Read-only. Never mutates files.
- Exits 1 on hard issues (schema failure, over-cap, stale, xref gap) so
  CI can gate on it.

## Expected Output

A structured report grouped by section. Each finding includes the path
and a short reason. A `Recommendations` block lists next-step commands
(e.g. `/library:cluster`, `/library:consolidate`, `/library:promote`).

## Implementation

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/library_lint.py" "${AI_CONTEXT_LIBRARY_PATH:-$PWD}"
```

## Safety Reminder

Never auto-commit fixes. Never auto-push. Surface findings to the user.
