---
name: detecting-durable-context
description: >
  Use when the user states something that should outlive this
  conversation — a stable preference, a decision plus its rationale, a
  fact about their infrastructure or project, or a procedure worth
  reusing — AND it is not already captured in the library. Do NOT use
  for questions, transient task state, speculation, or anything an
  existing memory already covers. Produces a PROPOSAL block; never
  writes.
---

# Detecting Durable Context

## Purpose
Catch memory-worthy context the moment it appears in conversation and
turn it into a validated, dedup-checked, contradiction-checked proposal
the user can approve in one word — so durable knowledge stops depending
on the user remembering to type /library:add-memory.

## When To Use
Fire when ALL of these hold:
- The user asserts something as true/decided/preferred, not asked.
- It is durable: still useful in a session next month.
- It is reusable: not specific to the current throwaway task.
- It is not already in the library (check index.md and run
  checking-for-duplicates).

Do NOT fire when:
- The statement is a question, a guess, or thinking-out-loud.
- It is transient task state ("the test is failing right now").
- It is a raw transcript fragment or a TODO ("fix this later").
- An existing memory already says it (propose an UPDATE only if the
  user is correcting that memory — then surface the contradiction).
- It contains a secret, key, token, or .env content — never propose it.

When the trigger is ambiguous, do NOT fire. A missed proposal costs one
slash command. A noisy one costs user trust in every skill.

## Inputs Expected
- The user's statement(s) from the current turn.
- index.md (for a fast "is this already known" pass).
- Read access to memories/** for confirmation.
- scripts/embed_query.py (via the dedup check in proposing-a-memory) —
  optional; degrade if unavailable.

## Procedure
1. Classify the statement against the memory `type` enum
   (user_preference, agent_instruction, project_context, decision,
   fact, workflow, security_note, troubleshooting_note). If nothing
   fits, do not fire.
2. Draft a durable, self-contained body (>= 40 chars, no transcript
   phrasing — it must pass the useful-content heuristic).
3. Infer scope, importance, and kebab-case tags. For tags, prefer
   vocabulary already present in index.md / neighbour memories.
4. Hand the draft to proposing-a-memory, which runs the duplicate and
   contradiction checks and emits the PROPOSAL block. If a near-
   duplicate (cosine >= 0.92) exists, it switches to proposing an
   UPDATE to that memory instead of a new one.
5. Stop. Wait for explicit human approval. Do not call any write tool.

## Output Format
A single PROPOSAL block (assembled by proposing-a-memory): type, scope,
importance, tags, target folder, title, body, dedup result,
contradiction result — followed by the question "Approve to write?" and
a one-line reminder that approval runs /library:add-memory, shows the
diff, and runs /library:review, but does not commit.

## Safety Checks
- Never call /library:add-memory, Write, or Edit from this skill.
- Refuse to propose anything matching a scan_secrets.py pattern.
- If the duplicate/contradiction checks are unavailable (Voyage AI
  unreachable, `VOYAGE_API_KEY` unset, or the LLM judge is not wired),
  still emit the proposal but label it "dedup/contradiction check
  UNAVAILABLE — verify manually or run /library:lint after commit".
  Never block on ML being down.
- Do not propose more than one memory per user turn unless the user
  clearly stated multiple distinct durable facts.

## Failure Modes
- Over-firing on transient state -> tighten by requiring an explicit
  assertion verb; when unsure, stay silent.
- Proposing a near-duplicate -> caught by the duplicate check in
  proposing-a-memory; if it still slips through, /library:lint
  orphan/cluster checks catch it.
- ML backend down -> proposal still emitted, labelled unverified;
  pipeline unaffected.
- Misclassified type -> user edits one frontmatter field at approval
  time; the edit is captured as feedback.
