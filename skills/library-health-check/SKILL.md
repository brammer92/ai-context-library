---
name: library-health-check
description: >
  Use when the user asks about the state of the AI context library —
  "what's in the library", "is the library healthy", "what's pending",
  "anything stale", "how big is the corpus", cap pressure, orphans, or
  embedding staleness. Read-only: it may run /library:status and
  /library:lint and report, but it mutates nothing.
---

# Library Health Check

## Purpose
Give the user a fast, read-only picture of the library's health without
them having to remember which slash command shows what. This is the one
Tier-1 skill: it may act (run read-only commands) without asking,
because it cannot change anything.

## When To Use
Fire when the user asks about library state, pending changes, staleness,
cap pressure, orphans, tag distribution, corpus size, or embedding
freshness.

Do NOT fire when:
- The user wants to ADD, EDIT, or REMOVE content — that is
  detecting-durable-context or a slash command, not this skill.
- The user asks a question answerable from a single file you already
  have open — just answer it.

## Inputs Expected
- No user-supplied input required.
- Read access to the library at $AI_CONTEXT_LIBRARY_PATH.

## Procedure
1. Run `/library:status` — branch, pending changes, memory/skill
   counts, validation summary, secret-scan summary.
2. Run `/library:lint` — schema integrity, stale claims, orphans,
   cross-reference gaps, cap pressure on the bounded files, tag
   distribution, recent activity.
3. If an embeddings/memories.jsonl exists, note its line count against
   the memory count as a rough embedding-freshness signal.
4. Summarise: what is healthy, what needs attention, and the single
   most useful next action (e.g. "3 memories over 90 days stale —
   consider /library:lint follow-up" or "MEMORY.md at 94% of cap —
   consider /library:promote / consolidation").

## Output Format
A short report:
- One line of headline state (branch, pending file count, corpus size).
- A bulleted list of anything that needs attention (empty list = "all
  green").
- One recommended next action.
No PROPOSAL block — this skill never proposes a write.

## Safety Checks
- Read-only. Never call Write, Edit, /library:add-memory,
  /library:add-skill, /library:promote, /library:commit, or any
  mutating command.
- Running /library:status and /library:lint without asking is allowed
  precisely because they cannot mutate anything. Do not extend this
  permission to any other command.
- If the library path is unset or missing, say so and stop — do not
  guess a path.

## Failure Modes
- Library path unset/missing -> report the problem, recommend setting
  $AI_CONTEXT_LIBRARY_PATH or running /library:init; do not guess.
- /library:lint reports hard failures -> surface them verbatim; do not
  attempt to fix them from this skill.
- embeddings/ absent -> report "embeddings not yet generated" as a note,
  not an error; the pipeline works without them.
