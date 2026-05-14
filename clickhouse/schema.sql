-- ai-context-library — ClickHouse schema
-- =====================================================================
-- ClickHouse is the QUERY CACHE tier of the embeddings/observability
-- layer. It is never on the write path: every table here is rebuildable
-- from the git repo (embeddings/memories.jsonl) or from append-only
-- event emission. If ClickHouse is wiped, one loader run restores it.
--
-- Apply on AURORA (srv-ubuntu01):
--   clickhouse-client --queries-file clickhouse/schema.sql
-- or over HTTP:
--   curl "$CLICKHOUSE_URL/" --data-binary @clickhouse/schema.sql
--
-- Connection defaults used by the scripts:
--   CLICKHOUSE_URL  (default http://localhost:8123)
-- =====================================================================

-- ---------------------------------------------------------------------
-- library_embeddings  —  MVP-ACTIVE
-- Populated by scripts/embed_load_clickhouse.py from the canonical
-- embeddings/memories.jsonl. One row per memory; ReplacingMergeTree
-- keeps only the newest row per id (latest embedded_at wins).
-- Column order/names match embed_load_clickhouse.to_clickhouse_row().
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS library_embeddings
(
    id            String,
    content_hash  String,
    model         LowCardinality(String),
    dim           UInt16,
    vector        Array(Float32),
    embedded_at   DateTime,
    type          LowCardinality(String),
    tags          Array(String)
)
ENGINE = ReplacingMergeTree(embedded_at)
ORDER BY id;

-- Nearest-neighbour query shape used by the dedup / contradiction /
-- cluster paths (cosineDistance over Array(Float32)):
--
--   SELECT id, type, 1 - cosineDistance(vector, {q:Array(Float32)}) AS cos
--   FROM library_embeddings
--   WHERE id != {self:String}
--   ORDER BY cos DESC
--   LIMIT 5;


-- ---------------------------------------------------------------------
-- library_events  —  DEFERRED (next phase: feedback loop + observability)
-- Append-only event stream: skill fires, command runs, memory lifecycle.
-- Scaffolded now so the schema is reviewed alongside the embeddings work;
-- no script writes to it yet.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS library_events
(
    ts          DateTime,
    event_type  LowCardinality(String),  -- skill_fired, command_run, memory_read,
                                         -- memory_written, memory_edited,
                                         -- memory_deleted, promoted, demoted, lint_run
    skill       LowCardinality(String),  -- '' if not a skill
    command     LowCardinality(String),  -- '' if not a command
    memory_id   String,
    detail      String,                  -- free-form JSON blob
    session_id  String
)
ENGINE = MergeTree
ORDER BY (ts, event_type);


-- ---------------------------------------------------------------------
-- library_ml_decisions  —  DEFERRED (next phase: contradiction / dedup)
-- One row per ML-assisted decision and what the user did with it. The
-- join of ml_output vs user_output is the entire feedback signal.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS library_ml_decisions
(
    ts          DateTime,
    component   LowCardinality(String),  -- contradiction, dedup, tag_assist, cluster
    memory_id   String,
    model       LowCardinality(String),  -- nomic-embed-text, haiku-4.5, sonnet-4.6
    ml_output   String,                  -- JSON: what the model proposed
    user_action LowCardinality(String),  -- accepted, rejected, modified, '' if pending
    user_output String,                  -- JSON: what the user actually chose
    latency_ms  UInt32,
    cost_usd    Float64
)
ENGINE = MergeTree
ORDER BY (ts, component);
