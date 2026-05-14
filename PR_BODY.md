# Skill-driven automation layer + embeddings layer (v0.2.0)

> Branch: `feat/skill-automation-embeddings-layer` → `main`
> _This file is the PR body. Use it to open the PR, then delete it — it
> is not meant to live in the repo long-term._

Implements the MVP cut of the approved design doc: a Superpowers-style
skill layer that auto-*invokes* (never auto-*acts*), plus the embeddings
layer that backs de-duplication. Every existing human gate is untouched:
no auto-commit, no auto-push, every canonical write still goes through
`/library:add-memory` → diff → `/library:review` → `/library:commit`.

**9 commits · 22 files · +1923/−35 · 152 tests passing (was 112) · `make validate` OK · `make scan` clean.**

---

## What I built

### Skill layer (auto-invocation, not auto-action)
- **`hooks/session_start_bootstrap.sh`** + a new `SessionStart` event in
  `hooks.json` — injects a short, text-only bootstrap: the library
  exists, which skills auto-activate and on what triggers, and the
  inviolable rules.
- **3 skills** under `skills/`:
  - `detecting-durable-context` — Tier 2; auto-fires on durable context,
    emits a PROPOSAL block, never writes.
  - `proposing-a-memory` — internal helper; centralises the dedup /
    secret-prescan / useful-content gates into one PROPOSAL shape.
  - `library-health-check` — Tier 1; read-only, may run
    `/library:status` + `/library:lint` unprompted.

### Embeddings layer
- **`scripts/embed_memory.py`** — stdlib-only Ollama embedder (`urllib`
  POST to `/api/embeddings`). Upserts one JSON line per memory into the
  canonical, git-tracked `embeddings/memories.jsonl`. `content_hash`
  over body+type+tags means unchanged memories are never re-embedded.
  `--backfill` prunes deleted memories.
- **`scripts/embed_load_clickhouse.py`** — loads the JSONL into the
  ClickHouse `library_embeddings` query cache (`INSERT … FORMAT
  JSONEachRow`). The cache is rebuildable from the repo — never a
  dependency.
- **`scripts/embed_query.py`** — the read side: nearest-neighbour lookup
  backing `proposing-a-memory`'s dedup step. ClickHouse `cosineDistance`
  with a brute-force local-JSONL cosine fallback, so dedup works with
  **zero ClickHouse**.
- **`hooks/post_write_embed.sh`** — after a memory write, refreshes the
  JSONL then syncs the cache. Added as a step in the PostToolUse chain,
  which is reordered to `validate → embed → index → diff` so the diff
  summary is the final picture.
- **`clickhouse/schema.sql`** — `library_embeddings` (MVP-active);
  `library_events` + `library_ml_decisions` scaffolded for the next
  phase.
- `common.py` and `init_library.py` updated so `embeddings/` is an
  allowed subtree and is scaffolded (with an explanatory README) in new
  libraries.

### Graceful degradation (a hard constraint of the design)
Every ML touchpoint degrades to a no-op: Ollama down → embed scripts
warn and exit 0, JSONL untouched; ClickHouse down → loader exits 0,
query falls back to local cosine. **The plugin still runs with zero ML
installed** — verified by tests, not just asserted.

### Verification done
- 40 new tests; all backend calls faked. Full suite 152 passing.
- End-to-end run against **stub Ollama + stub ClickHouse HTTP servers**
  (real `urllib` round-trips): `init → create_memory → embed_memory
  --backfill → embeddings/memories.jsonl → embed_load_clickhouse →
  ClickHouse rows`, plus `post_write_embed.sh` driving the full chain,
  plus `embed_query.py` returning ranked neighbours via the local
  fallback.
- Idempotency (unchanged memories not re-embedded), `--force` re-embed,
  and JSONL determinism confirmed.

---

## What I deferred

All deferred items are the design's explicit "ship next month / later"
roadmap — not surprises:

- **Contradiction detection on write** (the Haiku-tier LLM judge). The
  skills reference it; with no judge wired, `proposing-a-memory` marks
  the contradiction field `UNAVAILABLE` — the designed degradation.
- **`/library:cluster` embedding upgrade** (`library_cluster_embed.py`)
  — the stdlib tag-clustering still works.
- **Trust scoring** (`library_trust.py`, the `trust` frontmatter field)
  — deferred until there are enough contradiction/edit/promote signals
  to make the score non-random.
- **`embed-reconcile` GitHub Action** — on-push re-embed + drift report.
- **`library_events` / `library_ml_decisions`** — DDL is in
  `schema.sql`, but nothing emits to them yet (that's the feedback-loop
  + observability phase).
- **The other design skills** — `ingesting-a-source`,
  `detecting-skill-candidates`, `reviewing-before-commit`,
  `promoting-to-working-set`. `detecting-durable-context` alone proves
  the propose-don't-apply pattern.
- **Observability** — Grafana dashboard, n8n→Telegram alerts.
- **No Anthropic API calls in this MVP** — the tiered-routing policy is
  design-only so far; everything here is local (Ollama) or pure stdlib.

---

## Where I'm least confident

1. **No live Ollama/ClickHouse in the build environment.** Everything
   was verified against stdlib stub HTTP servers that mimic the API
   shapes. The real `nomic-embed-text` response shape, ClickHouse's
   `JSONEachRow` ingest of `Array(Float32)`, and `cosineDistance`
   haven't touched real services. These are standard APIs, but they
   need a real smoke test on AURORA:
   ```bash
   ollama pull nomic-embed-text
   curl "$CLICKHOUSE_URL/" --data-binary @clickhouse/schema.sql
   python3 scripts/embed_memory.py --backfill            # against the real hub
   python3 scripts/embed_load_clickhouse.py
   python3 scripts/embed_query.py --text "some durable statement"
   ```
2. **SessionStart hook output mechanism.** `session_start_bootstrap.sh`
   prints plain text to stdout. I believe Claude Code injects
   SessionStart stdout as context, but some CC versions expect a
   `hookSpecificOutput.additionalContext` JSON envelope. Worth
   confirming the bootstrap actually lands in context in a fresh
   session — if not, the fix is a one-line wrapper.
3. **`embedded_at` timezone.** The JSONL stores ISO-8601 `Z`; the loader
   converts to `YYYY-MM-DD HH:MM:SS` for ClickHouse `DateTime`, assuming
   UTC. Confirm against a real ClickHouse instance.
4. **Skill trigger precision.** The `description` triggers are written
   to be sharp with explicit do-not-fire clauses, but real false-fire /
   miss rates can only be tuned by dogfooding. In particular,
   `proposing-a-memory` being a non-triggering internal helper relies on
   the model respecting its "no standalone trigger" description.
5. **Plugin-skill vs library-skill path.** `pre_write_validate.sh` only
   validates skills under `$AI_CONTEXT_LIBRARY_PATH/skills/`, so the
   plugin's own CC-format skills are not validated by `validate_skill.py`
   in normal use. But if a user points `AI_CONTEXT_LIBRARY_PATH` *at the
   plugin repo itself*, that validator would (wrongly) reject these
   skills. Edge case, not hit in normal operation.
6. **Whole-JSONL ClickHouse sync per write.** `post_write_embed.sh`
   re-syncs the entire JSONL on each memory write rather than using
   `embed_load_clickhouse.py --only <id>`. Fine at the current corpus
   size; could lag at thousands of memories. `--only` exists and is
   tested — wiring it into the hook needs the hook to extract the
   memory id, which I left for a follow-up.

---

## Reviewer checklist
- [ ] `make test` (152), `make validate`, `make scan`
- [ ] Real smoke test on AURORA (command block above)
- [ ] Fresh Claude Code session: confirm the SessionStart bootstrap
      lands and `detecting-durable-context` fires on a stated preference
- [ ] Decide whether `embeddings/memories.jsonl` should be committed to
      the **hub** repo or `.gitignore`d there (this PR only touches the
      plugin repo; the design treats the JSONL as a committed artifact)
