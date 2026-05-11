---
description: Ingest a raw source (file path or URL) into the library — copy under sources/, discuss takeaways, and propose memories/skills.
argument-hint: <local-path or URL> [title="..."]
allowed-tools: Bash, Read, WebFetch
---

# /library:ingest

## Purpose

Bring a new raw source — an article, paper, transcript, or note — into the
AI context library. This is **Karpathy LLM Wiki's "ingest" operation**:
the human curates the source; the agent (Claude) reads it, discusses
takeaways, proposes structured memories/skills, and the user approves each
proposal before commit.

## Usage

```
/library:ingest path/to/article.md
/library:ingest https://example.com/article  title="Article Title"
```

## Behavior

1. Parse `$ARGUMENTS`. If it looks like a URL, use **WebFetch** to retrieve
   the content. Save the fetched body to a temporary local file under
   `/tmp/library-ingest-XXX.md`. If it looks like a path, use it directly.
2. Read the source content end-to-end.
3. Discuss the takeaways with the user (3-5 bullet points; what's novel,
   what conflicts with existing memories, what's actionable).
4. For each candidate memory, propose:
   - Type (`user_preference` / `security_note` / `decision` / …).
   - Tags (kebab-case).
   - Importance.
   - A draft body (durable, specific).
   The user approves each before you call `/library:add-memory`.
5. If the source describes a reusable procedure, propose
   `/library:add-skill` with a draft name + description.
6. Once at least one memory or skill is approved (and they have been
   created by the underlying scripts), copy the source into the library:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/library_ingest.py" \
       --source <local-path> \
       --title "<derived or user-provided title>" \
       --library "${AI_CONTEXT_LIBRARY_PATH:-$PWD}"
   ```

   The script copies the file to `sources/YYYY-MM-DD-<slug>.<ext>`, scans
   it for secrets, and appends an `ingest` entry to `log.md`.
7. Tell the user the file is not committed; suggest `/library:review`.

## Safety Rules

- **Never** fetch a URL behind authentication. If WebFetch returns 403 or
  401, abort and report it.
- **Never** ingest a file that contains secrets. The Python script's
  built-in scan will refuse; if it deletes the copy, surface the reason
  and stop.
- **Never** overwrite an existing source. The script will refuse on name
  collision.
- **Never** propose more than 3 candidate memories per source — quality
  over quantity.

## Expected Output

- A short summary of the source.
- 1-3 proposed memories with their `/library:add-memory` invocations.
- 0-1 proposed skills with their `/library:add-skill` invocations.
- A confirmation that the source was copied and logged.

## Safety Reminder

Never auto-commit. Never auto-push. Never silently save proposed memories
without explicit approval.
