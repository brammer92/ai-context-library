#!/usr/bin/env python3
"""Nearest-neighbour lookup over the embeddings layer — the read side.

This is the query helper that backs the dedup step of the
`proposing-a-memory` skill: given some text (or an existing memory id),
return the most similar memories so a near-duplicate can be caught
*before* a proposal reaches the user.

It runs brute-force cosine over the canonical
`embeddings/memories.jsonl` artifact — no external query service. That
keeps the plugin's only runtime dependencies plain Python + git. At
single-user, low-hundreds-of-memories scale, brute-force cosine is
sub-second per query.

Stdlib only. Graceful: if the embedder is unreachable the script cannot
embed the query, so it prints a note and exits 0 — it never breaks a
caller.

Usage:
    python scripts/embed_query.py --text "a durable statement" [--k 5]
    python scripts/embed_query.py --memory mem_20260514_foo [--json]

Exit codes:
    0  success, or a graceful skip (embedder down, no embeddings yet)
    2  bad invocation, or library path not found
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import common
import embed_memory
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


def nearest(
    vector: list[float], library: Path, *, k: int, exclude_id: str | None,
) -> list[dict]:
    """Return top-k nearest memories to ``vector``.

    Brute-force cosine over <library>/embeddings/memories.jsonl. The
    canonical artifact is the only query path — there is no external
    cache to fall back from.
    """
    jsonl_path = library / embed_memory.JSONL_REL
    return query_local_jsonl(vector, jsonl_path, k=k, exclude_id=exclude_id)


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

    hits = nearest(vector, library, k=args.k, exclude_id=exclude_id)

    if args.json:
        print(json.dumps(hits, separators=(",", ":")))
        return 0

    if not hits:
        print("no neighbours found (no embeddings generated yet, or empty corpus).")
        return 0

    print(f"nearest {len(hits)}:")
    for h in hits:
        tags = ",".join(h["tags"])
        print(f"  {h['cos']:.3f}  {h['id']}  [{h['type']}]  {tags}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
