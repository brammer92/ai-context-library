---
description: Create a structured, validated memory entry from the user's input.
argument-hint: <memory content to save>
allowed-tools: Bash, Read
---

# /library:add-memory

## Purpose

Create a new structured memory entry from the user's input. Validates the
result, scans it for secrets, and writes it to the correct folder under the
library. **Does not commit.**

## Usage

```
/library:add-memory The user prefers Docker Compose-first self-hosted deployments with strong security defaults.
```

## Behavior

1. Read `$ARGUMENTS` as the memory body.
2. Infer `--type` from the content. Allowed types:
   - `user_preference`, `agent_instruction`, `project_context`, `decision`,
     `fact`, `workflow`, `security_note`, `troubleshooting_note`.
3. If the type is ambiguous, ask the user to choose — do not guess for
   security-sensitive content.
4. Infer `--tags` (kebab-case) from key topics in the content.
5. Choose `--importance` (default `medium`; `high` for security/decisions).
6. Call `create_memory.py` with the inferred arguments.
7. Show the generated file path and the resulting `git diff`.
8. Tell the user the file is not committed and suggest `/library:review`.

## Safety Rules

- Refuse to save content that looks like a secret. The secret scanner runs
  automatically; if it fires, the file is deleted.
- Refuse to save transcript fragments (validated by the useful-content
  heuristic).
- Never overwrite an existing memory file.
- Never commit.

## Expected Output

A confirmation line with the new file path, the suggested next command
(`/library:review`), and a short summary of the inferred type/tags.

## Implementation

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/create_memory.py" \
  --content "$ARGUMENTS" \
  --type "<inferred>" \
  --tags "<inferred,comma,separated>" \
  --importance "<low|medium|high|critical>" \
  --library "${AI_CONTEXT_LIBRARY_PATH:-$PWD}"
```

If `--type` is unclear from the user's input, ask the user before invoking
the script. Pass `--dry-run` first if the user asks to preview.

## Safety Reminder

Never auto-commit. Never auto-push. Never overwrite without explicit approval.
