#!/usr/bin/env python3
"""Nearest-neighbour lookup over the embeddings layer — the read side.

This is the query helper that backs the dedup step of the
`proposing-a-memory` skill: given some text (or an existing memory id),
return the most similar memories so a near-duplicate can be caught
*before* a proposal reaches the user.

Two query paths, tried in order:
  1. ClickHouse `library_embeddings` via `cosineDistance` — fast, the
     normal path.
  2. Local cosine over `embeddings/memories.jsonl` — the fallback. It
     means dedup still works with ZERO ClickHouse: slower, but the
     canonical artifact is always enough.

Stdlib only. Graceful: if Ollama is unreachable the script cannot embed
the query, so it prints a note and exits 0 — it never breaks a caller.

Usage:
    python scripts/embed_query.py --text "a durable statement" [--k 5]
    python scripts/embed_query.py --memory mem_20260514_foo [--json]

Exit codes:
    0  success, or a graceful skip (Ollama down, no embeddings yet)
    2  bad invocation, or library path not found
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import common
import embed_memory
from embed_load_clickhouse import ClickHouseUnavailable, DEFAULT_CLICKHOUSE_URL, DEFAULT_TABLE
from embed_memory import OllamaUnavailable


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]. Returns 0.0 if either vector is zero."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def query_local_jsonl(
    vector: list[float], jsonl_path: Path, *, k: int, exclude_id: str | None,
) -> list[dict]:
    """Brute-force nearest neighbours over the canonical JSONL artifact."""
    records = embed_memory.load_jsonl(jsonl_path)
    hits: list[dict] = []
    for rid, rec in records.items():
        if exclude_id and rid == exclude_id:
            continue
        vec = rec.get("vector") or []
        hits.append({
            "id": rid,
            "type": rec.get("type", ""),
            "tags": rec.get("tags", []) or [],
            "cos": cosine(vector, vec),
        })
    hits.sort(key=lambda h: h["cos"], reverse=True)
    return hits[:k]


def query_clickhouse(
    vector: list[float], *, url: str, table: str, k: int, exclude_id: str | None,
) -> list[dict]:
    """Nearest neighbours via ClickHouse cosineDistance. Raises on failure."""
    vec_literal = "[" + ",".join(repr(float(x)) for x in vector) + "]"
    exclude = (exclude_id or "").replace("'", "")
    sql = (
        f"SELECT id, type, tags, 1 - cosineDistance(vector, {vec_literal}) AS cos "
        f"FROM {table} WHERE id != '{exclude}' "
        f"ORDER BY cos DESC LIMIT {int(k)} FORMAT JSON"
    )
    full_url = url.rstrip("/") + "/?" + urllib.parse.urlencode({"query": sql})
    req = urllib.request.Request(full_url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as exc:
        raise ClickHouseUnavailable(f"ClickHouse query failed: {exc}") from exc
    out = []
    for row in payload.get("data", []):
        out.append({
            "id": row.get("id", ""),
            "type": row.get("type", ""),
            "tags": row.get("tags", []) or [],
            "cos": float(row.get("cos", 0.0)),
        })
    return out


def nearest(
    vector: list[float], library: Path, *,
    k: int, exclude_id: str | None, clickhouse_url: str, table: str,
) -> tuple[list[dict], str]:
    """Return (hits, source). Tries ClickHouse, falls back to local JSONL."""
    try:
        hits = query_clickhouse(
            vector, url=clickhouse_url, table=table, k=k, exclude_id=exclude_id,
        )
        return hits, "clickhouse"
    except ClickHouseUnavailable:
        jsonl_path = library / embed_memory.JSONL_REL
        hits = query_local_jsonl(vector, jsonl_path, k=k, exclude_id=exclude_id)
        return hits, "local"


def _find_memory_body(library: Path, mem_id: str) -> tuple[str, str] | None:
    """Return (title, body) for a memory id, or None if not found."""
    memories_dir = library / "memories"
    if not memories_dir.is_dir():
        return None
    for path in memories_dir.rglob("*.md"):
        try:
            meta, body = common.parse_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if meta.get("id") == mem_id:
            return str(meta.get("title", "")), body
    return None


def main(argv: list[str] | None = None, *, embed_fn=None) -> int:
    parser = argparse.ArgumentParser(
        description="Nearest-neighbour lookup over the embeddings layer."
    )
    parser.add_argument("--text", default=None, help="Query text to embed and search with.")
    parser.add_argument("--memory", default=None,
                        help="Existing memory id; its body becomes the query (and is excluded).")
    parser.add_argument("--library", default=None,
                        help="Library root. Defaults to $AI_CONTEXT_LIBRARY_PATH or cwd.")
    parser.add_argument("--k", type=int, default=5, help="Number of neighbours to return.")
    parser.add_argument("--exclude", default=None, help="Memory id to exclude from results.")
    parser.add_argument("--clickhouse-url", default=DEFAULT_CLICKHOUSE_URL,
                        help=f"ClickHouse HTTP base URL (default: {DEFAULT_CLICKHOUSE_URL}).")
    parser.add_argument("--table", default=DEFAULT_TABLE,
                        help=f"ClickHouse table (default: {DEFAULT_TABLE}).")
    parser.add_argument("--ollama-host", default=embed_memory.DEFAULT_OLLAMA_HOST,
                        help="Ollama base URL.")
    parser.add_argument("--model", default=embed_memory.DEFAULT_MODEL, help="Embedding model.")
    parser.add_argument("--json", action="store_true", help="Emit results as JSON.")
    args = parser.parse_args(argv)

    if bool(args.text) == bool(args.memory):
        print("error: pass exactly one of --text or --memory.", file=sys.stderr)
        return 2

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    exclude_id = args.exclude
    if args.memory:
        found = _find_memory_body(library, args.memory)
        if found is None:
            print(f"error: memory '{args.memory}' not found under memories/.", file=sys.stderr)
            return 2
        title, body = found
        query_text = f"{title}\n\n{body.strip()}".strip()
        if exclude_id is None:
            exclude_id = args.memory
    else:
        query_text = args.text

    if embed_fn is None:
        def embed_fn(text: str) -> list[float]:  # noqa: E306
            return embed_memory._ollama_embed(text, model=args.model, host=args.ollama_host)

    try:
        vector = embed_fn(query_text)
    except OllamaUnavailable as exc:
        print(
            f"note: cannot run a similarity query — {exc}. The caller should "
            f"treat dedup as UNAVAILABLE and proceed.",
            file=sys.stderr,
        )
        if args.json:
            print("[]")
        return 0

    hits, source = nearest(
        vector, library, k=args.k, exclude_id=exclude_id,
        clickhouse_url=args.clickhouse_url, table=args.table,
    )
    if source == "local":
        print("note: ClickHouse unavailable; used the local JSONL cosine fallback.",
              file=sys.stderr)

    if args.json:
        print(json.dumps(hits, separators=(",", ":")))
        return 0

    if not hits:
        print("no neighbours found (no embeddings generated yet, or empty corpus).")
        return 0

    print(f"nearest {len(hits)} (source: {source}):")
    for h in hits:
        tags = ",".join(h["tags"])
        print(f"  {h['cos']:.3f}  {h['id']}  [{h['type']}]  {tags}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
