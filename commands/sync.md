---
description: Pull the latest AI context library changes from GitHub (fast-forward only). Aborts if there are uncommitted changes.
allowed-tools: Bash, Read
---

# /library:sync

## Purpose

Pull the latest changes from the configured GitHub remote. Aborts if the
working tree has uncommitted changes — this command never rewrites local
work.

## Usage

```
/library:sync
```

## Behavior

1. `cd "${AI_CONTEXT_LIBRARY_PATH:-$PWD}"`.
2. If not a git repo, print guidance and exit.
3. Check `git status --short`. If non-empty, warn the user and stop.
4. Run `git pull --ff-only`. Surface the result.
5. After a successful pull, re-run validation on every memory/skill file
   to confirm the synced library is still valid.
6. Report final status.

## Safety Rules

- Never run destructive git commands (`reset --hard`, `clean -fd`,
  `push --force`, `filter-branch`, `gc --prune=now`, `rebase`,
  `checkout -- .`).
- Never overwrite local changes.
- Refuse to pull if the working tree is dirty.

## Expected Output

Either:

- A short summary of the pull (commits applied, files changed), followed by
  validation status, or
- A refusal message explaining why the pull was skipped (dirty tree, not a
  git repo, non-fast-forward).

## Implementation

```
cd "${AI_CONTEXT_LIBRARY_PATH:-$PWD}"
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "not a git repo; run /library:init then 'git init' first" 1>&2
  exit 1
fi
if [ -n "$(git status --short)" ]; then
  echo "working tree has uncommitted changes — commit or stash first" 1>&2
  exit 1
fi
git pull --ff-only
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/library_status.py" .
```

## Safety Reminder

Never auto-commit. Never auto-push. Never run destructive git commands.
