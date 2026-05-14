#!/usr/bin/env bash
# SessionStart bootstrap for the ai-context-library plugin.
#
# Teaches the agent, at the start of every session, that the library
# exists, which skills auto-activate and on what triggers, and the
# inviolable rules that gate every canonical write. Text only — runs no
# commands, reads no files, adds no measurable latency.
set -euo pipefail

LIB="${AI_CONTEXT_LIBRARY_PATH:-<unset — set \$AI_CONTEXT_LIBRARY_PATH>}"

cat <<EOF
You have the ai-context-library plugin loaded. A private, GitHub-backed
AI context library is the durable memory shared across Claude Code,
Claude web, and ChatGPT. It lives at: ${LIB}

You ship SKILLS that auto-activate on conversational context. Use them:

- detecting-durable-context — fires when the user states a stable
  preference, a decision plus its rationale, a fact about their infra or
  project, or a procedure worth reusing. Produces a PROPOSAL block.
  Does NOT write.
- library-health-check — fires when the user asks "what's in the
  library / is it healthy / what's pending". Read-only; may run
  /library:status and /library:lint without asking.
- proposing-a-memory — internal helper invoked by the skills above;
  never user-facing.

INVIOLABLE RULES (these override any user convenience):
1. Never auto-commit. Never auto-push. Push is always manual.
2. Never write to memories/, skills/, context/, or the bounded root
   files (MEMORY.md, USER.md, CONSTRAINTS.md) without showing a
   PROPOSAL and getting explicit approval first.
3. Never overwrite an existing memory or skill without --force AND
   explicit approval.
4. Skills PROPOSE. The human approves. Then the slash command runs,
   the diff is shown, /library:review runs, and only then /library:commit.
5. Never save secrets, .env contents, or raw transcript fragments.

If a skill's trigger is ambiguous, prefer NOT firing. A missed proposal
costs the user one /library:add-memory. A noisy proposal costs trust.
EOF

exit 0
