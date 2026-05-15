---
description: Advisory LLM secret audit over pending AI context library changes — defense-in-depth on top of the deterministic regex scanner. Never blocks a commit.
allowed-tools: Bash, Read
---

# /library:audit

## Purpose

Run the advisory LLM secret auditor (`scripts/audit_secrets_llm.py`) over
every pending change in the AI context library. The auditor classifies
each file as `clean`, `suspicious`, `likely_secret`, or `UNAVAILABLE`.

## Usage

```
/library:audit
```

## Behavior

1. `cd "${AI_CONTEXT_LIBRARY_PATH:-$PWD}"` and check for a git repo.
2. List changed files via `git diff --name-only HEAD` plus untracked
   files, filtered to `memories/`, `skills/`, `context/`, or the
   bounded root files (`MEMORY.md`, `USER.md`, `CONSTRAINTS.md`).
3. For each candidate file, run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit_secrets_llm.py" --file "$f"
   ```
4. Summarize per-file verdicts. Flag `suspicious` and `likely_secret`
   for human eyeball. `UNAVAILABLE` means the judge could not be
   reached (missing `ANTHROPIC_API_KEY`, network down, or garbled
   response) — treat the file as "not audited" and proceed.

## Safety Rules

- This is an ADVISORY check. It NEVER blocks a write or a commit on
  its own.
- The deterministic `scan_secrets.py` regex scanner remains the only
  blocking gate. If the LLM auditor and the scanner disagree, the
  scanner wins for blocking; the LLM's concern is surfaced for human
  review.
- A `suspicious` or `likely_secret` verdict is a warning, not a
  failure. The user decides whether to revise the file or proceed.
- If `ANTHROPIC_API_KEY` is unset or the network is down, every
  verdict will be `UNAVAILABLE`. That is the correct, honest behaviour
  — never fabricate `clean`.

## Implementation

```
cd "${AI_CONTEXT_LIBRARY_PATH:-$PWD}"
CHANGED="$(git diff --name-only HEAD; git ls-files --others --exclude-standard)"
echo "$CHANGED" | sort -u | while IFS= read -r f; do
  [[ -z "$f" || ! -f "$f" ]] && continue
  case "$f" in
    memories/*|skills/*|context/*|MEMORY.md|USER.md|CONSTRAINTS.md)
      python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit_secrets_llm.py" --file "$f" || true
      ;;
  esac
done
```

After running, summarize the verdicts. Tell the user:
- `clean` files need no action.
- `suspicious` files deserve a manual re-read.
- `likely_secret` files should be revised before commit — but the
  regex scanner in `/library:review` is the only thing that will
  actually refuse a commit.
- `UNAVAILABLE` means the audit did not run; not a failure.

## Safety Reminder

Never auto-commit. Never auto-push. This command is read-only and
advisory.
