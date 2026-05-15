# AI Context Library Plugin

A Claude Code plugin that safely writes validated memories, reusable skills,
and durable context into a private GitHub-based AI context library. Designed
so the same library can be read by Claude Code, Claude web UI, ChatGPT, and
any other agent with a GitHub connector.

The plugin is **not** a RAG system. It is a structured, audited write
pipeline: detect durable context → propose → validate → secret-scan →
write → diff → human review → approve → commit. Each risky step has an
explicit human gate.

---

## Table of Contents

1. [What this plugin does](#what-this-plugin-does)
2. [Why GitHub as the context library](#why-github-as-the-context-library)
3. [The Hermes 5-pillar harness](#the-hermes-5-pillar-harness)
4. [The Karpathy LLM Wiki layers](#the-karpathy-llm-wiki-layers)
5. [The skill layer (auto-invocation)](#the-skill-layer-auto-invocation)
6. [The embeddings layer](#the-embeddings-layer)
7. [ML-assisted library maintenance](#ml-assisted-library-maintenance)
8. [How this works with Claude Code](#how-this-works-with-claude-code)
9. [How this works with Claude web UI](#how-this-works-with-claude-web-ui)
10. [How this works with ChatGPT](#how-this-works-with-chatgpt)
11. [Installation](#installation)
12. [Environment variables](#environment-variables)
13. [Expected context library structure](#expected-context-library-structure)
14. [Slash commands](#slash-commands)
15. [Bounded working-set memory](#bounded-working-set-memory)
16. [Auto-maintained indexes](#auto-maintained-indexes)
17. [Ingesting sources](#ingesting-sources)
18. [How validation works](#how-validation-works)
19. [How secret scanning works](#how-secret-scanning-works)
20. [Safety model](#safety-model)
21. [Recommended workflow](#recommended-workflow)
22. [GitHub setup](#github-setup)
23. [Troubleshooting](#troubleshooting)
24. [Future enhancements](#future-enhancements)
25. [License](#license)

---

## What this plugin does

- Writes structured Markdown + YAML frontmatter files into a separate
  context-library repository.
- Validates every memory against [`schemas/memory.schema.json`](schemas/memory.schema.json)
  and every skill against [`schemas/skill.schema.json`](schemas/skill.schema.json).
- Scans every write for likely secrets (GitHub PATs, OpenAI keys, AWS
  credentials, PEM private keys, generic credential patterns, raw `.env`
  files).
- Shows the resulting `git diff` after every write.
- Refuses to commit if validation or secret scanning fails.
- Never pushes to GitHub. The user pushes manually.
- Provides slash commands so the workflow is explicit and auditable.

---

## Why GitHub as the context library

GitHub is the smallest common denominator across the agents you already use:

- **Claude Code** can read any file in the working directory.
- **Claude web UI** has a GitHub connector for repos.
- **ChatGPT** has a GitHub connector for repos.
- **Other agents** (Cursor, Aider, Cody) can clone a public/private repo
  and read it directly.

Storing your AI context as plain Markdown in a GitHub repository means every
agent reads the same source of truth. Git gives you history, branches, and
review. There is no proprietary store, no vector database to maintain, and
no vendor lock-in.

---

## The Hermes 5-pillar harness

The plugin implements the [Hermes Agent](https://hermesatlas.com/guide/)
"harness engineering" model from Nous Research. The core idea: **the LLM
is a replaceable component; the harness is the asset.** Five layers
surround the LLM, each enforced by specific files and commands:

| # | Pillar | Files / commands |
| --- | --- | --- |
| 1 | **Instructions** | `CLAUDE.md`, `AGENTS.md`, `CHATGPT.md`, `context/*.md` |
| 2 | **Constraints** | `CONSTRAINTS.md` (≤ 4000 chars) — hard guardrails |
| 3 | **Feedback** | `/library:lint` (retrospective + health check), the append-only `log.md` |
| 4 | **Memory** | Bounded working set: `MEMORY.md` (≤ 2200 chars) + `USER.md` (≤ 1375 chars). Archive: `memories/**/*.md` |
| 5 | **Orchestration** | `skills/*/SKILL.md` + `/library:cluster` to surface skill candidates |

The small character caps on the working-set files are deliberate. They
force consolidation rather than junk accumulation — when `MEMORY.md`
fills up, you must demote something into the archive before adding more.
`/library:promote` and `/library:consolidate` (via `cluster`) are the
explicit gestures for moving content between the two tiers.

## The Karpathy LLM Wiki layers

The plugin also implements
[Karpathy's "LLM Wiki"](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
three-layer architecture and its three operations.

| Layer | Folder / file | What it holds |
| --- | --- | --- |
| **Layer 1: Raw sources** | `sources/` | Immutable original documents (articles, papers, transcripts). Tracked in git so connected agents read them via GitHub. |
| **Layer 2: The wiki** | `memories/`, `skills/`, `context/`, `projects/`, `prompts/` | LLM-generated structured Markdown with cross-references. |
| **Layer 3: The schema** | `CLAUDE.md`, `AGENTS.md`, `CHATGPT.md`, `CONSTRAINTS.md`, `schemas/` | Configuration that defines wiki structure and conventions. |

Three operations:

- **Ingest** — `/library:ingest <path-or-url>`. Read a source, discuss
  takeaways with the user, propose memories/skills/context updates, then
  copy the source to `sources/` and log the operation.
- **Query** — implicit: any agent reads the library through GitHub or
  through Claude Code's filesystem tools. `index.md` makes this efficient.
- **Lint** — `/library:lint`. Schema integrity, stale claims, orphans,
  cross-reference gaps, cap pressure, tag distribution, recommendations.

Two auto-maintained index files:

- **`index.md`** — content catalog grouped by section, one line per page.
  Regenerated on every write via the PostToolUse hook (or manually with
  `/library:index`).
- **`log.md`** — append-only chronological record. Newest entries at top.
  Every write under the library subtree gets logged automatically.

## The skill layer (auto-invocation)

The plugin ships **skills** that auto-activate on conversational context
— so durable context gets *proposed* the moment it appears, instead of
depending on the user remembering to type a slash command. This follows
the Superpowers model: **automation means automatic _invocation_, not
automatic _action_.** Skills propose; humans still gate every write.

A `SessionStart` hook (`hooks/session_start_bootstrap.sh`) injects a
short bootstrap at the start of every session: that the library exists,
which skills auto-activate and on what triggers, and the inviolable
rules (no auto-commit, no auto-push, no silent writes, no overwrite
without `--force`). It is text only — it runs no commands and adds no
measurable latency.

| Skill | Tier | Trigger (sharp `When To Use`) |
| --- | --- | --- |
| `detecting-durable-context` | 2 — auto-invoke, propose only | The user *states* a stable preference, a decision plus rationale, an infra/project fact, or a reusable procedure — and it is not already in the library. Never fires on questions, transient task state, or transcript fragments. |
| `proposing-a-memory` | internal helper | Invoked by `detecting-durable-context` to assemble the validated, dedup-checked, contradiction-checked PROPOSAL block. No standalone trigger. |
| `library-health-check` | 1 — auto-act (read-only) | The user asks about library state, staleness, cap pressure, pending changes, corpus size. May run `/library:status` and `/library:lint` unprompted because they cannot mutate anything. |

**Three auto-invocation tiers:**

- **Tier 1 — auto-act (read-only).** May run read-only commands without
  asking. Mutates nothing. (`library-health-check`)
- **Tier 2 — auto-invoke, propose only.** May read and run read-only ML,
  and may emit a PROPOSAL block — but may not call any tool that writes.
  (`detecting-durable-context`)
- **Tier 3 — approval before every write.** The slash commands
  (`/library:add-memory`, `/library:commit`, …) run only after explicit
  human approval of a specific proposal.

The "propose, don't apply" turn: a skill auto-fires → emits a PROPOSAL
block → the human approves → the slash command runs → the diff is shown
→ `/library:review` runs → and only then `/library:commit`. Push remains
manual. Skills shorten the distance to a proposal; they never shorten
the distance to a commit.

## The embeddings layer

An optional embeddings sidecar gives Claude Code nearest-neighbour
lookup for de-duplication and contradiction candidate detection —
**without** any local service, **without** a vector database, and
**without** polluting the canonical Markdown. The plugin runs as plain
Python + git; everything else (Voyage, Anthropic, GitHub) is cloud.

- **Model.** `voyage-3.5` (1024-dim) via Voyage AI — the
  Anthropic-recommended embedding provider. `LIBRARY_EMBED_MODEL` lets
  you pick a different Voyage model (e.g. `voyage-3.5-lite` for lower
  cost or `voyage-4-large` for higher quality).
- **Canonical artifact.** `embeddings/memories.jsonl` — one git-tracked
  JSON line per memory (`id`, `content_hash`, `model`, `dim`,
  `embedded_at`, `type`, `tags`, `vector`). Deterministic and
  diff-friendly. Reviewed and committed like any other file — never
  auto-committed.
- **Query path.** Brute-force cosine over the JSONL directly
  (`scripts/embed_query.py`). No external query service. At single-user
  / low-hundreds-of-memories scale, sub-second per query.
- **Freshness.** Each line carries a `content_hash` over the memory
  body + type + tags. An unchanged memory is never re-embedded, so the
  JSONL stays byte-stable. The record's `model` field is also checked:
  if the configured embedding model changed, the corpus auto-re-embeds
  on the next backfill — backend swaps migrate without `--force`.
- **Hooks.** After a memory write, `hooks/post_write_embed.sh` refreshes
  the JSONL via `scripts/embed_memory.py`. Backfill an existing corpus
  with `python3 scripts/embed_memory.py --backfill`.
- **Privacy posture.** Memory text is sent to Voyage AI under your
  configured `VOYAGE_API_KEY`. This is the explicit, configured cloud
  routing — high-volume embedding stays cheap (~$0.06/1M tokens for
  `voyage-3.5`), and nothing else local is required.
- **Graceful degradation.** If Voyage is unreachable or
  `VOYAGE_API_KEY` is unset, the embed scripts warn and exit 0 — the
  memory write and every existing pipeline step are unaffected. The
  plugin keeps working with zero ML installed.

**Cross-agent note:** the vectors are *Claude Code infrastructure*.
Claude web and ChatGPT cannot run nearest-neighbour search and get no
*direct* benefit from `embeddings/memories.jsonl` — they read the raw
Markdown via their GitHub connectors as before. The benefit to them is
*indirect*: a dedup'd, contradiction-checked corpus is a cleaner corpus
for all three agents.

## ML-assisted library maintenance

Four scripts use the embeddings layer to actively improve the corpus.
**Every one is deterministic where it can be, fully tested without a
live backend, degrades gracefully, and only ever *suggests* — none
mutate canonical files except `library_trust.py --apply`, which still
goes through the normal review/commit gate.**

| Script | What it does | Confidence basis |
| --- | --- | --- |
| `embed_query.py` | Nearest-neighbour lookup for a draft or a memory id (brute-force cosine over the canonical JSONL). | Pure cosine math; fully tested. |
| `library_cluster_embed.py` | Embedding near-duplicate clustering — groups paraphrased memories that share meaning but not tags. Backs `/library:cluster --embeddings`; falls back to tag clustering. | Deterministic union-find over cosine; fully tested. |
| `embed_tag_suggest.py` | Auto-tag assist — ranks the tags of a draft's nearest neighbours. Rules + NN, not a trained classifier. | Deterministic given the neighbour set; fully tested. |
| `library_trust.py` | Trust scoring — a transparent weighted formula (importance + references + promotion − age decay) written to a `trust` frontmatter field. Dry-run by default. | No model — an auditable formula; every weight is a legible constant. |
| `library_contradict.py` | Contradiction candidate detection — embedding-NN narrowing into "likely"/"possible" bands, plus an **optional, pluggable** Haiku-tier LLM judge (`--judge`, needs `ANTHROPIC_API_KEY`). | Narrowing is deterministic and tested; the LLM verdict is advisory and degrades to `UNAVAILABLE` — it never fabricates a "no contradiction". |

The LLM judge in `library_contradict.py` is the **one** component whose
*output quality* is not verifiable without a live API smoke test — by
design it is opt-in and its absence degrades to an honest non-answer.
Everything else is deterministic and verified end-to-end.

## How this works with Claude Code

1. Install this plugin (see [Installation](#installation)).
2. Set `AI_CONTEXT_LIBRARY_PATH` to the path of your local clone of the
   context library (e.g. `~/ai-context-hub`).
3. In any Claude Code session, when Claude identifies durable context worth
   saving, it proposes `/library:add-memory ...` or `/library:add-skill
   ...`. **It does not save silently.**
4. The slash commands run validation + secret scanning, write to the
   library, and show a diff.
5. You run `/library:review`, then `/library:commit`, then push manually.

A small project-level `CLAUDE.md` can point Claude at the shared library:

```markdown
# CLAUDE.md
Use my shared AI context library as the source of truth.
Context library path: `/home/me/ai-context-hub`
Before making architectural decisions, check AGENTS.md,
context/working-style.md, context/coding-standards.md,
context/security-principles.md, memories/, skills/.
When durable context is discovered, propose a `/library:add-memory` update.
When reusable procedures are discovered, propose a `/library:add-skill` update.
Do not silently save memories. Do not save secrets.
```

---

## How this works with Claude web UI

In Claude web UI, enable the GitHub connector and grant access to your
private `ai-context-hub` repository. Reference it directly in a prompt:

> "Read AGENTS.md, context/security-principles.md, and the memories under
> memories/security/ before answering."

Claude web UI can read but not write to GitHub through the connector. To
write new memories, use Claude Code with this plugin and commit + push
afterward.

---

## How this works with ChatGPT

ChatGPT's GitHub connector also reads private repos. Add `CHATGPT.md` at
the repo root with the same intent as `CLAUDE.md` — point at `AGENTS.md`,
`context/`, `memories/`, and `skills/` as the source of truth. Like Claude
web UI, ChatGPT reads but does not write; use the Claude Code plugin for
writes.

---

## Installation

```bash
# Option A — install from a local checkout (development).
/plugin install /path/to/ai-context-library

# Option B — install from a GitHub marketplace.
/plugin marketplace add brammer92/ai-context-library
/plugin install library@ai-context-library
```

Then set the library path (in your shell rc):

```bash
export AI_CONTEXT_LIBRARY_PATH="$HOME/ai-context-hub"
```

The plugin works out of the box with default settings; you only need
`AI_CONTEXT_LIBRARY_PATH` to point at your library clone.

**Manifest location note:** the plugin manifest lives at
[`.claude-plugin/plugin.json`](.claude-plugin/plugin.json), which is the
Claude Code convention.

---

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AI_CONTEXT_LIBRARY_PATH` | current working directory | Path to your local context library clone. |
| `AI_CONTEXT_LIBRARY_DEFAULT_AGENT_SCOPE` | `*` | Default `agent_scope` written to new entries. |
| `AI_CONTEXT_LIBRARY_DEFAULT_SOURCE` | `claude-code` | Default `source` attribution. |
| `AI_CONTEXT_LIBRARY_REQUIRE_REVIEW` | `true` | Refuse to commit unless `/library:review` has been run. |
| `AI_CONTEXT_LIBRARY_ALLOW_AUTO_COMMIT` | `false` | Permit `/library:commit` without an explicit review step. |
| `AI_CONTEXT_LIBRARY_ALLOW_PUSH` | `false` | Documented only — the plugin never pushes regardless of this value. |
| `VOYAGE_API_KEY` | _(unset)_ | Required for embeddings. Unset → embedding hooks exit 0 with a warning; the rest of the pipeline runs unaffected. |
| `LIBRARY_EMBED_MODEL` | `voyage-3.5` | Voyage embedding model. Examples: `voyage-3.5-lite` (lower cost), `voyage-4-large` (higher quality). |
| `VOYAGE_BASE_URL` | `https://api.voyageai.com` | Voyage API base URL (override only if proxying). |
| `ANTHROPIC_API_KEY` | _(unset)_ | Optional. When set with `library_contradict.py --judge`, runs the Haiku LLM judge over contradiction candidates. Also used by `audit_secrets_llm.py` (the advisory secret auditor wired into `/library:review`). Unset → verdicts are `UNAVAILABLE`. |
| `LIBRARY_AUDIT_MODEL` | `claude-haiku-4-5-20251001` | Anthropic model for the advisory secret auditor in `audit_secrets_llm.py`. |

Defaults are safe: no auto-commit, no auto-push, validation required,
secret scanning required, human review required. The embeddings layer is
optional — if `VOYAGE_API_KEY` is unset, the embedding hooks degrade
gracefully and the rest of the pipeline is unaffected.

---

## Expected context library structure

When `/library:init` runs against an empty directory, it creates:

```text
ai-context-hub/
  README.md
  CLAUDE.md
  AGENTS.md
  CHATGPT.md

  context/
    user-profile.md
    working-style.md
    coding-standards.md
    security-principles.md
    infrastructure-preferences.md
    project-decisions.md
    glossary.md

  memories/
    user/
    agents/
    projects/
    decisions/
    workflows/
    security/
    troubleshooting/

  skills/
  projects/
  prompts/
  templates/
    memory-entry.md
    skill-template.md
    decision-record.md
    project-template.md
  schemas/
    memory.schema.json
    skill.schema.json
  embeddings/
    README.md
    memories.jsonl   # generated by the embeddings layer; not created by init
```

Existing files are never overwritten.

---

## Slash commands

### Base commands

| Command | Purpose |
| --- | --- |
| `/library:init` | Create missing folders/starter files in the library. Never overwrites. |
| `/library:add-memory <text>` | Generate, validate, scan, and write a structured memory file. |
| `/library:add-skill <description>` | Generate a skill folder (SKILL.md + examples.md + validation.md). |
| `/library:review` | Validate + secret-scan every pending change. Also runs the advisory LLM secret auditor (informational only). |
| `/library:audit` | Run the advisory LLM secret auditor over pending changes. Advisory only — never blocks a commit. |
| `/library:commit` | Commit reviewed changes. Refuses if validation or the regex secret scan fails. |
| `/library:sync` | `git pull --ff-only` and re-validate. Aborts if dirty. |
| `/library:status` | Print branch, pending changes, counts, validation, cap usage, and findings. |

### Harness + wiki commands

| Command | Purpose |
| --- | --- |
| `/library:ingest <path-or-url>` | Karpathy ingest — bring a raw source into `sources/`, discuss takeaways, propose memories/skills. |
| `/library:lint` | Merged lint + Hermes retrospective — schema integrity, stale claims, orphans, cross-refs, cap pressure, tag distribution. |
| `/library:cluster` | Merged Hermes pattern detection + consolidation proposals — surfaces tag clusters and suggests skills or merges. |
| `/library:promote <mem_id>` | Copy a memory's reference into `MEMORY.md` (cap-enforced). |
| `/library:index` | Manual regeneration of `index.md`. The hook does this automatically on every write. |

### How to add a memory

```
/library:add-memory The user prefers Docker Compose-first self-hosted deployments with strong security defaults.
```

Claude infers `--type` (`security_note` here), `--tags`, and `--importance`;
asks before guessing on ambiguous content; writes to
`memories/security/mem_YYYYMMDD_<slug>.md`; shows the diff; does not commit.

### How to add a skill

```
/library:add-skill Create a skill for reviewing Docker Compose files for security issues.
```

Generates `skills/docker-compose-security-review/{SKILL.md, examples.md,
validation.md}` with all seven required sections. Refuses to overwrite.

### How to review changes

```
/library:review
```

Validates every pending memory/skill file, scans every changed file for
secrets, and prints a per-file status table.

### How to commit changes

```
/library:commit
```

Runs review first. If clean, stages only paths under allowed library
subtrees, generates a Conventional Commits message, and asks for explicit
approval before running `git commit`. Never pushes.

### How to sync from GitHub

```
/library:sync
```

Aborts if the working tree is dirty. Otherwise runs `git pull --ff-only` and
re-validates the synced library.

### How to inspect status

```
/library:status
```

Prints library path, branch, sanitized remote, pending changes, memory and
skill counts, validation summary, secret-scan findings, and a recommended
next action.

---

## Bounded working-set memory

Three files at the library root carry hard character caps:

| File | Cap | Purpose |
| --- | --- | --- |
| `MEMORY.md` | 2200 | Current focus — the 1-3 things you're actively working on, recent decisions worth keeping in front of every agent, open questions. |
| `USER.md` | 1375 | Stable user preferences — identity, working style, non-negotiables. Anything situational goes in `memories/` instead. |
| `CONSTRAINTS.md` | 4000 | Hard guardrails every agent must obey. Project-wide and user-wide rules. |

The caps are deliberately small. Hermes's rationale: when the working
set fills up, you are forced to consolidate before adding more — this
keeps every agent's read-time context tight and high-signal. The full
archive of older or less-active content lives under `memories/`, where
there is no cap.

Two commands move content between the two tiers:

- **`/library:promote <mem_id>`** — append a short reference to a
  memory inside `MEMORY.md` under a chosen section. Refuses if the
  result would exceed the cap.
- **`/library:cluster`** — surface candidates for consolidation
  (multiple memories sharing tags) or for skill extraction (procedure-
  like tags appearing in 5+ memories).

Cap usage is reported by `/library:status` and `/library:lint`.

## Auto-maintained indexes

Two files at the library root are auto-maintained by the plugin:

- **`index.md`** — content catalog. One section per content type
  (Working Set, Memories, Skills, Context, Sources, Projects, Prompts),
  each entry as `- [title](relative/path.md) — one-line summary`. The
  output is deterministic — regenerating with no library changes
  produces byte-identical output. Used by agents (and humans) to locate
  content without scanning every folder.
- **`log.md`** — append-only chronological record. Each entry starts
  with `## [YYYY-MM-DD HH:MM:SSZ] <operation> | <subject>`. Newest at
  top. Captures `init`, `ingest`, `write`, `promote`, `lint`, and any
  manual operations that call `library_log.append`.

The PostToolUse hook `hooks/post_write_index.sh` triggers a log append
and an index regeneration after every write under the library subtree
(memories, skills, context, sources, prompts, templates, schemas,
projects, and the bounded root files). The hook never auto-commits — it
only updates the index. Manual entry points are `/library:index` and
the underlying `scripts/library_log.py`.

## Ingesting sources

The `sources/` directory is Karpathy's Layer 1 — immutable raw
documents you want the library to compound around. Articles, papers,
transcripts, internal notes, anything you want available verbatim.

The workflow is `/library:ingest <local-path>` or
`/library:ingest <url>`:

1. If a URL is given, Claude fetches it via WebFetch and writes the
   body to a temporary local file.
2. Claude reads the content end-to-end and discusses takeaways with
   you (3-5 bullets).
3. Claude proposes 1-3 candidate memories using the exact
   `/library:add-memory` syntax. You approve each before invocation.
4. If the source describes a reusable procedure, Claude proposes a
   `/library:add-skill` invocation.
5. Once at least one memory or skill has been created, the source is
   copied into `sources/YYYY-MM-DD-<slug>.<ext>` and an entry is
   appended to `log.md`.

The Python script scans the source for secrets before logging — if any
fire, the copy is deleted and the script exits non-zero.

**Copyright caveat:** because `sources/` is committed to GitHub
(per the plugin's default), do not ingest material you do not have the
right to redistribute. The plugin does not filter for license — that's
your judgment call.

## How validation works

### Memory validation rules ([scripts/validate_memory.py](scripts/validate_memory.py))

- File starts with YAML frontmatter delimited by `---`.
- Required keys: `id, title, type, scope, agent_scope, tags, importance,
  created_at, updated_at, source`.
- `id` matches `^mem_[a-z0-9_]+$` (snake_case).
- `type` ∈ `{user_preference, agent_instruction, project_context, decision,
  fact, workflow, security_note, troubleshooting_note}`.
- `scope` ∈ `{global, agent, project, private}`.
- `agent_scope` is a non-empty list of strings.
- `tags` are kebab-case.
- `importance` ∈ `{low, medium, high, critical}`.
- `created_at` and `updated_at` are ISO-8601.
- `source` is non-empty.
- The Markdown body is non-empty, ≥ 40 measurable characters, and does
  not look like a transcript fragment (no `maybe`/`todo`/`tbd`/`temporary`/
  `we discussed`/`let's`/`note:`/`fix this later` lead-in).

### Bounded-file validation rules ([scripts/validate_bounded.py](scripts/validate_bounded.py))

Applied to `MEMORY.md`, `USER.md`, and `CONSTRAINTS.md`.

- File has YAML frontmatter with `updated_at` (ISO-8601) and `cap` (int).
- Declared `cap` matches the registered cap for the filename.
- Markdown body length is at most the registered cap.

### Skill validation rules ([scripts/validate_skill.py](scripts/validate_skill.py))

- Required keys: `id, name, version, description, status, tags,
  agent_scope, risk_level, created_at, updated_at`.
- `id` matches `^skill_[a-z0-9_]+$`.
- `version` is semver (`^\d+\.\d+\.\d+$`).
- `status` ∈ `{draft, active, deprecated}`.
- `risk_level` ∈ `{low, medium, high}`.
- The body contains all seven required sections: `Purpose`, `When To Use`,
  `Inputs Expected`, `Procedure`, `Output Format`, `Safety Checks`,
  `Failure Modes`.

---

## How secret scanning works

[`scripts/scan_secrets.py`](scripts/scan_secrets.py) walks a file or
directory, skipping these directories:

- `.git/`, `node_modules/`, `__pycache__/`
- `.venv/`, `venv/`
- `.pytest_cache/`, `.mypy_cache/`
- `dist/`, `build/`
- `tests/` — for the plugin's own repo, where test fixtures contain
  fake-shaped credentials on purpose. **User libraries should not
  contain a top-level `tests/`**; if you put real content there it
  will be silently un-scanned. The library convention puts everything
  under `memories/`, `skills/`, `context/`, etc., never `tests/`.

It also skips binary files and `.env.example` / `.env.sample` /
`.env.template`.

Patterns flagged:

- `ghp_…` (GitHub classic PAT)
- `github_pat_…` (GitHub fine-grained PAT)
- `sk-…` (OpenAI-style key)
- `xoxb-` / `xoxp-` (Slack tokens)
- `AKIA[0-9A-Z]{16}` (AWS access key id)
- `aws_secret_access_key = …` (AWS secret)
- `OPENAI|ANTHROPIC|GITHUB|GITLAB|NPM|AZURE|GOOGLE_*_(TOKEN|KEY|SECRET) = …`
- `password|passwd|secret|token|api_key|apikey = …`
- `-----BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----`
- Any file named `.env` or `.env.<env>` (excluding the example variants).

Findings print as `path:line:pattern_name: <redacted>`. The redaction
preserves the first 3 and last 4 characters; the middle is replaced with
at least four asterisks. The full secret never appears in output.

The scanner is the **only blocking secret gate** in the pipeline.
`create_memory.py` and `library_ingest.py` write to a tempfile in
`$TMPDIR` first, run the scan against the tempfile, and only
`os.replace()` into the library tree once the scan is clean — so failed
content never lands under the watched library subtree.

---

## LLM secret auditor (advisory)

[`scripts/audit_secrets_llm.py`](scripts/audit_secrets_llm.py) is a
defense-in-depth advisory layer on top of the regex scanner. It asks
Anthropic Haiku to classify a file as `clean`, `suspicious`,
`likely_secret`, or `UNAVAILABLE`. It is wired into `/library:review`
and exposed standalone as `/library:audit`.

- **Advisory only.** The auditor never blocks a write or a commit on
  its own. The regex scanner remains the only gate. A `suspicious` or
  `likely_secret` verdict surfaces to the user; the user decides.
- **Honest non-answers.** Missing `ANTHROPIC_API_KEY`, network failure,
  or a garbled judge response → verdict is `UNAVAILABLE`. Never
  fabricates `clean`.
- **Prompt-injection hardening.** Content under audit is wrapped in
  `<<<CONTENT>>>...<<<END>>>` markers and the prompt frames it as data
  to inspect, not instructions to follow. Standard hardening, not
  bulletproof.
- **Stdlib only.** A single `urllib` POST to
  `https://api.anthropic.com/v1/messages`. No extra dependencies.
- **Cost shape.** One Haiku call per file at `/library:review` time —
  bounded by deliberate review batches, not per-write. `LIBRARY_AUDIT_MODEL`
  overrides the model.

---

## Safety model

- **Never automatically push to GitHub.** Push is always manual.
- **Never automatically commit without explicit approval.** Even
  `/library:commit` asks for confirmation of the message and file list.
- **Never save secrets.** The scanner runs before commit and on every
  hook-triggered write; the creator deletes its own output if findings fire.
- **Never save raw `.env` content.** Files named `.env` are flagged.
- **Never save private keys or session cookies.** PEM patterns are flagged.
- **Never run destructive Git commands.** No `git reset --hard`, no
  `git clean -fd`, no `git push --force`, no `git filter-branch`, no
  `git gc --prune=now`, no `git rebase`, no `git checkout -- .`.
- **Never overwrite existing memories or skills without `--force`.**
- **Prefer proposed patches over silent writes.** The slash commands are
  the only intended write path.
- **Keep context concise and durable.** The useful-content heuristic
  rejects transcript fragments.

---

## Recommended workflow

```text
1.  Claude Code identifies durable context.
2.  User runs /library:add-memory or /library:add-skill.
3.  Plugin generates structured Markdown into a tempfile in $TMPDIR.
4.  Plugin validates the tempfile.
5.  Plugin scans the tempfile for secrets.
6.  Plugin os.replace()'s the tempfile into the library tree (atomic;
    failed content never lands in the watched library subtree).
7.  Plugin shows the Git diff.
8.  User runs /library:review (regex scan + advisory LLM audit).
9.  User approves changes.
10. User runs /library:commit.
11. User manually pushes to GitHub.
12. Claude Code, Claude web UI, and ChatGPT can all read the updated context.
```

---

## GitHub setup

```bash
mkdir -p ~/ai-context-hub && cd ~/ai-context-hub
AI_CONTEXT_LIBRARY_PATH="$PWD" python3 /path/to/plugin/scripts/init_library.py
git init
git add .
git commit -m "chore: initialize AI context hub"
git remote add origin git@github.com:brammer92/ai-context-hub.git
git push -u origin main
```

Use a **private** repository. Enable branch protection if multiple agents
or humans write to it. Never commit secrets — the plugin will refuse, but
GitHub itself is the last line of defense.

---

## Troubleshooting

**The slash commands don't appear in Claude Code.**
Run `/plugin list` and verify the plugin is enabled. The manifest must be
at `.claude-plugin/plugin.json` (not at the repository root).

**`/library:add-memory` fails with "content is too short".**
The useful-content heuristic rejects bodies under 40 characters or that
look like transcript fragments. Rewrite the content as a durable, specific
statement.

**`/library:commit` refuses with "secret findings".**
Run `python scripts/scan_secrets.py <file>` to see which pattern fired.
Rewrite the file to remove the secret; if it was a false positive,
restructure the text to avoid the pattern (the scanner is conservative on
purpose).

**`/library:sync` reports "uncommitted changes".**
Commit or stash your local changes first. The plugin will never overwrite
local work.

**Validation passes locally but fails in CI.**
Make sure both environments run Python 3.11+. The plugin uses no external
dependencies.

---

## Future enhancements

Shipped:

- The [skill layer](#the-skill-layer-auto-invocation) — SessionStart
  bootstrap + auto-invoking skills.
- The [embeddings layer](#the-embeddings-layer) —
  `embeddings/memories.jsonl` sidecar, Voyage AI embeddings, no local
  service.
- [ML-assisted library maintenance](#ml-assisted-library-maintenance) —
  embedding near-duplicate clustering, auto-tag assist, deterministic
  trust scoring, and contradiction candidate detection (with an
  optional, pluggable Anthropic LLM judge).

Still ahead:

- **Wiring the LLM judge into `proposing-a-memory`** — and a live API
  smoke test of its verdict quality (the judge mechanism ships now;
  trusting its output does not, yet).
- **An `embed-reconcile` GitHub Action** — re-embeds drift on push and
  reports staleness, without committing anything itself.
- **Trust signal enrichment** — feeding contradiction counts and
  explicit confirmations into `library_trust.py` once a feedback-event
  stream exists.
- Optional multi-root libraries; a `--push` opt-in; legacy-format
  migration helpers; a web dashboard.
- Holographic Reduced Representation retrieval — deferred; no
  demonstrated win over cosine at the current corpus scale.

---

## License

MIT — see [LICENSE](LICENSE).
