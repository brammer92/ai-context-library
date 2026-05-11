---
description: Review pending AI context library changes — validate, scan for secrets, and report whether they are safe to commit.
allowed-tools: Bash, Read
---

# /library:review

## Purpose

Review every pending change in the AI context library before commit. Runs
schema validation on changed memory/skill files and a full secret scan on
changed files. **Does not commit.**

## Usage

```
/library:review
```

## Behavior

1. `cd "${AI_CONTEXT_LIBRARY_PATH:-$PWD}"` and check for a git repo.
2. List changed files via `git diff --name-only HEAD` plus untracked files.
3. For each changed file:
   - If it's under `memories/*.md`, run `validate_memory.py`.
   - If it's under `skills/*/SKILL.md`, run `validate_skill.py`.
   - Run `scan_secrets.py` on the file.
4. Summarize:
   - File count (changed / valid / failing / secret findings).
   - Per-file status with first error line for any failure.
5. If any failure, print remediation guidance and refuse to recommend
   commit.
6. If clean, print the recommended next command: `/library:commit`.

## Safety Rules

- Refuse to recommend commit if validation fails.
- Refuse to recommend commit if any secret pattern fires.
- Refuse to recommend commit if any changed path is outside the allowed
  library subtree.

## Expected Output

A status table and either:

- A clear "READY to commit" message with the suggested command, or
- A list of failures with remediation steps.

## Implementation

```
cd "${AI_CONTEXT_LIBRARY_PATH:-$PWD}"
CHANGED="$(git diff --name-only HEAD; git ls-files --others --exclude-standard)"
echo "$CHANGED" | sort -u | while IFS= read -r f; do
  [[ -z "$f" || ! -f "$f" ]] && continue
  case "$f" in
    memories/*.md) python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_memory.py" "$f" || true ;;
    skills/*/SKILL.md) python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_skill.py" "$f" || true ;;
  esac
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan_secrets.py" "$f" || true
done
```

After running, summarize the results to the user in a short status block.

## Safety Reminder

Never auto-commit. Never auto-push. This command is read-only.
