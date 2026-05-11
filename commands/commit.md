---
description: Commit validated AI context library changes after running review. Refuses to commit if validation or secret scan fails.
allowed-tools: Bash, Read
---

# /library:commit

## Purpose

Commit validated changes to the AI context library. Runs `/library:review`
behavior first; refuses to commit on any failure. **Never pushes.**

## Usage

```
/library:commit
```

## Behavior

1. Run review checks (validation + secret scan) on every changed file.
2. If any check fails, print remediation steps and exit without committing.
3. Stage only paths under allowed library subtrees:
   - `CLAUDE.md`, `AGENTS.md`, `CHATGPT.md`, `README.md`
   - `context/`, `memories/`, `skills/`, `projects/`, `prompts/`,
     `templates/`, `schemas/`
4. Refuse to stage anything outside those paths.
5. Refuse to stage any file matching the secret-scan filename rules
   (`.env`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519`, `secrets/`, `private/`).
6. Generate a Conventional Commits message inferred from the change types:
   - new memory: `feat(memory): add <id>` or `chore(memory): update <id>`
   - new skill: `feat(skill): add <id>`
   - context update: `docs(context): update <file>`
   - schema/template: `chore(schema): update`
7. Show the user the proposed message and the staged file list and ask for
   explicit confirmation before running `git commit`.
8. Run `git commit -m "<message>"`. Do not push.

## Safety Rules

- Refuse to commit if validation fails.
- Refuse to commit if the secret scanner finds anything.
- Refuse to stage files outside the allowed subtree.
- Never run `git push`. Never run any destructive git command.
- Never use `--amend`, `--force`, or `--no-verify`.

## Expected Output

Either:

- A confirmation prompt with the proposed commit message and file list,
  followed by the commit hash once approved, or
- A refusal message listing what needs to be fixed first.

## Implementation

1. Read `${AI_CONTEXT_LIBRARY_PATH:-$PWD}` as the library root.
2. Run the review pipeline (same as `/library:review`).
3. If clean, show the user the proposed message + file list and wait for
   approval before running:

```
cd "${AI_CONTEXT_LIBRARY_PATH:-$PWD}"
git add -- <each-allowed-path>
git commit -m "<inferred message>"
```

4. After the commit succeeds, remind the user to `git push` manually when
   they are ready. The plugin will not push for them.

## Safety Reminder

Never auto-commit without explicit user approval of the message and file
list. Never auto-push. Never bypass hooks.
