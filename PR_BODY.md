# Skill layer + embeddings layer + ML-assisted maintenance (v0.2.0)

> Branch: `feat/skill-automation-embeddings-layer` → `main`
> _This file is the PR body. Use it to open the PR, then delete it — it
> is not meant to live in the repo long-term._

Implements the design doc's automation + ML work in three coherent
layers: a Superpowers-style **skill layer** that auto-*invokes* (never
auto-*acts*), an **embeddings layer**, and **ML-assisted maintenance**
that uses the embeddings to actively improve the corpus. Every existing
human gate is untouched: no auto-commit, no auto-push, every canonical
write still goes through `/library:add-memory` → diff →
`/library:review` → `/library:commit`.

**14 commits · ~30 files · 202 tests passing (was 112) · `make validate` OK · `make scan` clean · all scripts compile.**

---

## What I built

### Skill layer (auto-invocation, not auto-action)
- `hooks/session_start_bootstrap.sh` + a new `SessionStart` event —
  injects a short, text-only bootstrap (library exists, which skills
  fire on what triggers, the inviolable rules).
- **4 skills** under `skills/`:
  - `detecting-durable-context` — Tier 2; auto-fires on durable context,
    emits a PROPOSAL block, never writes.
  - `proposing-a-memory` — internal helper; centralises the dedup /
    tag-assist / contradiction / secret-prescan gates into one PROPOSAL.
  - `checking-for-contradictions` — internal helper; runs the
    contradiction check, surfaces candidates with resolution options.
  - `library-health-check` — Tier 1; read-only, may run
    `/library:status` + `/library:lint` unprompted.

### Embeddings layer
- `scripts/embed_memory.py` — stdlib Ollama embedder → canonical,
  git-tracked `embeddings/memories.jsonl`. `content_hash` over
  body+type+tags means unchanged memories are never re-embedded.
- `scripts/embed_load_clickhouse.py` — loads the JSONL into the
  ClickHouse `library_embeddings` query cache (rebuildable, never a
  dependency).
- `scripts/embed_query.py` — nearest-neighbour read side; ClickHouse
  `cosineDistance` with a brute-force local-JSONL fallback.
- `hooks/post_write_embed.sh` — after a memory write, refreshes the
  JSONL then syncs the cache. PostToolUse chain reordered to
  `validate → embed → index → diff`.
- `clickhouse/schema.sql` — `library_embeddings` (active);
  `library_events` + `library_ml_decisions` scaffolded for observability.
- `common.py` + `init_library.py` updated so `embeddings/` is an allowed
  subtree and is scaffolded in new libraries.

### ML-assisted library maintenance (the "ML improves the project" work)
- `scripts/library_cluster_embed.py` — embedding near-duplicate
  clustering (union-find over pairwise cosine); catches paraphrased
  dupes tag-clustering misses. Backs `/library:cluster --embeddings`,
  falls back to tag clustering.
- `scripts/embed_tag_suggest.py` — auto-tag assist; ranks the tags of a
  draft's nearest neighbours. Rules + NN, not a trained classifier.
- `scripts/library_trust.py` — trust scoring as a transparent weighted
  formula (importance + references + promotion − age decay) → `trust`
  frontmatter field. Dry-run by default; `--apply` still goes through
  the review/commit gate.
- `scripts/library_contradict.py` — contradiction candidate detection:
  deterministic embedding-NN narrowing into "likely"/"possible" bands,
  plus an **optional, pluggable** Haiku-tier LLM judge (`--judge` +
  `ANTHROPIC_API_KEY`) that degrades to an honest `UNAVAILABLE`.
- `commands/cluster.md` updated for `--embeddings`.

### Graceful degradation (a hard design constraint)
Every ML touchpoint degrades to a no-op or an honest non-answer: Ollama
down → embed/query/suggest/contradict scripts warn and exit 0;
ClickHouse down → loaders exit 0, queries fall back to local cosine;
no LLM judge → contradiction verdicts are `UNAVAILABLE`, never a
fabricated "no conflict". **The plugin runs with zero ML installed** —
verified by tests, not asserted.

### Verification done
- **202 tests** (was 112; +90 new), all written test-first (RED→GREEN),
  all backend/API calls faked or stubbed.
- **End-to-end** against stub Ollama + stub ClickHouse HTTP servers
  (real `urllib` round-trips): `init → create_memory → embed --backfill
  → JSONL → load ClickHouse`, the full `post_write_embed.sh` chain, and
  all four ML scripts producing correct output — `library_cluster_embed`
  correctly grouped two paraphrased memories; `embed_query`,
  `embed_tag_suggest`, `library_contradict` all ran clean with the
  local fallback.
- Idempotency, `--force` re-embed, JSONL determinism, and
  `library_trust --apply` output re-validating against `validate_memory`
  all confirmed.

---

## What I deferred

- **Wiring the LLM judge into the live skill flow.** `library_contradict.py`
  ships the judge as a working, pluggable component, but `--judge` is
  opt-in and `proposing-a-memory` currently treats verdicts as advisory.
  Promoting it to a default needs the smoke test below.
- **`embed-reconcile` GitHub Action** — on-push re-embed + drift report.
- **`library_events` / `library_ml_decisions`** — DDL is in
  `schema.sql`, but nothing emits to them yet (the observability +
  feedback-loop phase).
- **Trust signal enrichment** — `library_trust.py` uses importance,
  references, promotion, and age today; contradiction counts and
  explicit confirmations wait on the event stream.
- **The remaining design skills** — `ingesting-a-source`,
  `detecting-skill-candidates`, `reviewing-before-commit`,
  `promoting-to-working-set`.
- **Observability** — Grafana dashboard, n8n→Telegram alerts.

---

## Where I'm least confident

1. **The LLM judge's verdict *quality*.** `library_contradict.py`'s
   `_anthropic_judge` is the one component whose output correctness I
   could not verify — no API access in the build environment. Its
   *mechanism* (request shape, orchestration, graceful degradation) is
   fully stub-tested; its *judgments* are not. By design it is opt-in
   and degrades to `UNAVAILABLE`, so an untested/wrong judge never
   silently corrupts the corpus — but do a live smoke test before
   trusting verdicts:
   ```bash
   ANTHROPIC_API_KEY=... python3 scripts/library_contradict.py \
       --text "we dropped macvlan for the syslog stack" --judge --library "$HUB"
   ```
2. **No live Ollama/ClickHouse in the build environment.** Verified
   against stdlib stub HTTP servers mimicking the API shapes. The real
   `nomic-embed-text` response, ClickHouse `JSONEachRow` ingest of
   `Array(Float32)`, and `cosineDistance` need a real smoke test on
   AURORA:
   ```bash
   ollama pull nomic-embed-text
   curl "$CLICKHOUSE_URL/" --data-binary @clickhouse/schema.sql
   python3 scripts/embed_memory.py --backfill
   python3 scripts/embed_load_clickhouse.py
   python3 scripts/embed_query.py --text "some durable statement"
   python3 scripts/library_cluster_embed.py
   python3 scripts/library_trust.py            # dry-run
   ```
3. **SessionStart hook output mechanism.** `session_start_bootstrap.sh`
   prints plain text to stdout; some CC versions expect a
   `hookSpecificOutput.additionalContext` JSON envelope. Confirm the
   bootstrap lands in context in a fresh session — one-line fix if not.
4. **Trust formula weights.** The *mechanism* is solid and fully tested;
   the specific weights (`IMPORTANCE_BONUS`, `AGE_DECAY_MAX`, …) are a
   judgment call. They are legible module constants, easy to tune, and
   the score is advisory — never a gate.
5. **`embedded_at` timezone** — ISO-Z → `YYYY-MM-DD HH:MM:SS` assuming
   UTC; confirm against a real ClickHouse instance.
6. **Skill trigger precision** — descriptions are written sharp with
   explicit do-not-fire clauses, but real false-fire/miss rates can only
   be tuned by dogfooding.

---

## Reviewer checklist
- [ ] `make test` (202), `make validate`, `make scan`
- [ ] Real smoke test on AURORA — the command block in §2 above
- [ ] LLM judge smoke test — the command in §1 above
- [ ] Fresh Claude Code session: confirm the SessionStart bootstrap
      lands and `detecting-durable-context` fires on a stated preference
- [ ] Decide whether `embeddings/memories.jsonl` is committed to the
      **hub** repo or `.gitignore`d there (this PR only touches the
      plugin repo)
