---
description: Detect tag clusters across memories and propose skill extraction or consolidation. Read-only — output is suggestions, not mutations.
argument-hint: [--min-cluster N]
allowed-tools: Bash, Read
---

# /library:cluster

## Purpose

Surface repeated patterns in the memory archive. Merged Hermes pillars 3
and 5 (feedback + orchestration): when the same tag appears across many
memories, that's a candidate for skill extraction; when overlapping tags
appear in multiple memories, that's a consolidation candidate.

## Usage

```
/library:cluster
/library:cluster --min-cluster 3
```

## Behavior

1. Load every memory's tag set.
2. Group memories by single tag and by tag-pair.
3. For each cluster of size ≥ `--min-cluster` (default 5), report:
   - The tag(s).
   - The member memories.
4. For each cluster, propose either:
   - A `/library:add-skill` invocation if the tag is procedure-like
     (`review`, `audit`, `checklist`, `workflow`, `procedure`,
     `playbook`, `runbook`, `template`).
   - A consolidation suggestion otherwise.

## Safety Rules

- Read-only. Never mutates memories.
- Proposals are suggestions; the user reviews and chooses what to act on.

## Expected Output

A report listing single-tag clusters, tag-pair clusters, and a list of
proposed next actions. The user can take any subset (or none).

## Implementation

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/library_cluster.py" \
    "${AI_CONTEXT_LIBRARY_PATH:-$PWD}" \
    --min-cluster 5
```

## Safety Reminder

Never auto-create skills. Never auto-merge memories. Surface proposals;
the user decides.
