---
name: proposing-a-memory
description: >
  Internal helper. Invoked by detecting-durable-context (and, later,
  ingesting-a-source) to turn a drafted memory into a validated,
  dedup-checked, contradiction-checked PROPOSAL block. Not user-facing —
  do not invoke this directly in response to a user message; it has no
  standalone trigger. Never writes; only assembles the proposal.
---

# Proposing a Memory

## Purpose
Take a drafted memory (body + inferred frontmatter) and assemble the
single PROPOSAL block the user approves. Centralises the dedup check,
the contradiction check, the auto-tag assist, and the secret pre-scan so
every proposing path produces the same shape and the same gates.

## When To Use
Only as an internal helper, invoked by another skill that has already
drafted a candidate memory. It has no conversational trigger of its own.
If you are reaching for this skill directly from a user message, you
want detecting-durable-context instead.

## Inputs Expected
- A draft: candidate body text plus inferred `type`, `scope`,
  `importance`, `tags`, and `title`.
- index.md and read access to memories/** .
- Optional: ClickHouse library_embeddings for nearest-neighbour lookup.
  Treat as best-effort — absence must not block the proposal.

## Procedure
1. Secret pre-scan: reject the draft outright if the title or body
   matches any scan_secrets.py pattern. Do not emit a proposal for it.
2. Useful-content check: the body must clear the useful-content
   heuristic (>= 40 chars, not a transcript fragment). If it fails, ask
   the user to restate rather than proposing a stub.
3. Duplicate check: embed the draft and query ClickHouse
   library_embeddings for the nearest existing memories.
   - cosine >= 0.92 -> switch to proposing an UPDATE to that memory.
   - 0.85-0.92 -> include the near-match in the proposal as context.
   - If ClickHouse/Ollama is down -> mark dedup "UNAVAILABLE".
4. Auto-tag assist: collect tags from the nearest neighbours; suggest
   any that fit and are not already on the draft. Skip silently if the
   neighbour lookup was unavailable.
5. Contradiction check: for the nearest neighbours, flag any that
   conflict with the draft. If the contradiction backend is down, mark
   it "UNAVAILABLE" rather than asserting "none".
6. Resolve the target folder from `type` via the memory-type -> folder
   map.
7. Emit exactly one PROPOSAL block. Stop. Wait for approval.

## Output Format
```
  ┌─ PROPOSAL: memory ──────────────────────────────────────────┐
  │ type:       <type>      scope: <scope>  importance: <imp>   │
  │ tags:       <kebab, comma-separated>                         │
  │ folder:     memories/<folder>/                               │
  │ title:      <title>                                          │
  │ body:       <durable, self-contained body>                   │
  │ dedup:      <no near-duplicates | UPDATE mem_x | UNAVAILABLE> │
  │ contradicts:<none | mem_x ... | UNAVAILABLE>                  │
  └──────────────────────────────────────────────────────────────┘
  Approve to write?  (approval runs /library:add-memory, shows the
  diff, and runs /library:review — nothing commits without /library:commit)
```

## Safety Checks
- Never call /library:add-memory, Write, or Edit. This skill only
  assembles text.
- Never claim "no contradictions" / "no duplicates" when the backend
  was unreachable — say "UNAVAILABLE".
- Never emit a proposal that failed the secret pre-scan or the
  useful-content check.
- One proposal per invocation.

## Failure Modes
- ClickHouse/Ollama down -> dedup and auto-tag degrade to UNAVAILABLE;
  the proposal is still emitted and the user can run /library:lint
  later.
- Contradiction backend down -> contradiction field is UNAVAILABLE; the
  proposal proceeds.
- Draft fails useful-content -> no proposal; ask the user to restate.
- Draft contains a secret -> no proposal; tell the user what pattern
  matched (redacted) and stop.
