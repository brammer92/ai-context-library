#!/usr/bin/env python3
"""Auto-tag assist — suggest tags for a draft memory from its neighbours.

When a memory is being drafted, the most consistent tags are usually the
ones already used by the most similar existing memories. This script
embeds the draft text, finds its nearest neighbours (via embed_query's
brute-force cosine over the JSONL artifact), and ranks the neighbours'
tags by frequency.

It is rules + nearest-neighbour, NOT a trained classifier: deterministic
given the neighbour set, and fully testable without a backend. It only
*suggests* — the proposing-a-memory skill still puts every tag in front
of the user for approval.

Usage:
    python scripts/embed_tag_suggest.py --text "draft body" [--existing a,b]

Exit codes:
    0  success, or a graceful skip (embedder unavailable)
    2  bad invocation, or library path not found
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import common
import embed_memory
import embed_query
from embed_memory import EmbedUnavailable


def suggest_tags(
    neighbours: list[dict], *, existing_tags: list[str],
    max_suggestions: int, min_count: int,
) -> list[dict]:
    """Rank kebab-case tags across `neighbours` by frequency.

    Excludes tags already on the draft, anything that is not kebab-case,
    and anything seen fewer than `min_count` times. Returns a
    deterministic list of ``{"tag": str, "count": int}`` — ordered by
    count desc, then tag asc.
    """
    existing = set(existing_tags)
    counter: Counter[str] = Counter()
    for n in neighbours:
        for tag in n.get("tags", []) or []:
            if not isinstance(tag, str):
                continue
            if tag in existing or not common.is_kebab_case(tag):
                continue
            counter[tag] += 1
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    out = [{"tag": t, "count": c} for t, c in ranked if c >= min_count]
    return out[:max_suggestions]


def main(argv: list[str] | None = None, *, embed_fn=None) -> int:
    parser = argparse.ArgumentParser(
        description="Suggest tags for a draft memory from its nearest neighbours."
    )
    parser.add_argument("--text", default=None, help="Draft memory text to suggest tags for.")
    parser.add_argument("--library", default=None,
                        help="Library root. Defaults to $AI_CONTEXT_LIBRARY_PATH or cwd.")
    parser.add_argument("--existing", default="",
                        help="Comma-separated tags already on the draft (excluded from suggestions).")
    parser.add_argument("--k", type=int, default=5, help="Neighbours to consider.")
    parser.add_argument("--max", dest="max_suggestions", type=int, default=5,
                        help="Maximum tags to suggest.")
    parser.add_argument("--min-count", type=int, default=1,
                        help="Minimum neighbour occurrences for a tag to be suggested.")
    parser.add_argument("--voyage-url", default=embed_memory.DEFAULT_VOYAGE_URL)
    parser.add_argument("--model", default=embed_memory.DEFAULT_MODEL)
    parser.add_argument("--json", action="store_true", help="Emit suggestions as JSON.")
    args = parser.parse_args(argv)

    if not args.text:
        print("error: --text is required.", file=sys.stderr)
        return 2

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    existing_tags = [t.strip() for t in args.existing.split(",") if t.strip()]

    if embed_fn is None:
        voyage_key = os.environ.get("VOYAGE_API_KEY", "")

        def embed_fn(text: str) -> list[float]:  # noqa: E306
            return embed_memory._voyage_embed(
                text, key=voyage_key, model=args.model,
                base_url=args.voyage_url, input_type="document",
            )

    try:
        vector = embed_fn(args.text)
    except EmbedUnavailable as exc:
        print(
            f"note: tag assist unavailable — {exc}. The caller should infer "
            f"tags directly and proceed.",
            file=sys.stderr,
        )
        if args.json:
            print("[]")
        return 0

    hits = embed_query.nearest(vector, library, k=args.k, exclude_id=None)
    suggestions = suggest_tags(
        hits, existing_tags=existing_tags,
        max_suggestions=args.max_suggestions, min_count=args.min_count,
    )

    if args.json:
        print(json.dumps(suggestions, separators=(",", ":")))
        return 0

    if not suggestions:
        print("no tag suggestions (no similar memories, or all their tags "
              "are already on the draft).")
        return 0

    print(f"suggested tags (from {len(hits)} neighbours):")
    for s in suggestions:
        print(f"  {s['tag']}  ({s['count']} neighbour(s))")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
