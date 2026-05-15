#!/usr/bin/env python3
"""Embedding-based near-duplicate clustering over the memory archive.

The stdlib `library_cluster.py` groups memories by shared *tags*. That
misses paraphrased near-duplicates that share meaning but not tags. This
script closes that gap: it groups memories whose embedding vectors are
above a cosine-similarity threshold, so the user can spot "I wrote this
twice in different words" and consolidate.

It is deterministic — pure cosine math over the canonical
`embeddings/memories.jsonl` artifact. No LLM, no live backend required.
If there is no embeddings artifact yet, it falls back to the stdlib
tag-based clustering so `/library:cluster` always returns something
useful.

Output is suggestion-only — nothing is mutated.

Usage:
    python scripts/library_cluster_embed.py [<library>] [--threshold 0.92]

Exit codes:
    0  success (report printed)
    2  bad invocation, or library path not found
"""
from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

import common
import embed_memory
import library_cluster
from embed_query import cosine

DEFAULT_THRESHOLD = 0.92


def near_duplicate_groups(records: dict[str, dict], *, threshold: float) -> list[dict]:
    """Group memory ids whose vectors are pairwise-linked above `threshold`.

    A union-find merge means a transitive chain (a~b, b~c) lands in one
    group even if a~c is weaker. Returns a deterministic, sorted list of
    ``{"members": [...sorted ids...], "max_cos": float}`` for every group
    with at least two members.
    """
    ids = sorted(records)
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in combinations(ids, 2):
        c = cosine(records[a].get("vector") or [], records[b].get("vector") or [])
        if c >= threshold:
            union(a, b)

    grouped: dict[str, list[str]] = {}
    for i in ids:
        grouped.setdefault(find(i), []).append(i)

    out: list[dict] = []
    for members in grouped.values():
        if len(members) < 2:
            continue
        members = sorted(members)
        max_cos = max(
            cosine(records[a].get("vector") or [], records[b].get("vector") or [])
            for a, b in combinations(members, 2)
        )
        out.append({"members": members, "max_cos": round(max_cos, 6)})

    out.sort(key=lambda g: g["members"][0])
    return out


def _print_report(groups: list[dict], *, threshold: float, library: Path) -> None:
    print(f"AI Context Library — embedding near-duplicate report ({library})")
    print(f"Cosine threshold: {threshold}")
    print("=" * 60)
    if not groups:
        print("\nNear-duplicate groups: none above threshold.")
        return
    print(f"\nNear-duplicate groups ({len(groups)}):")
    for g in groups:
        print(f"  group (max cosine {g['max_cos']}):")
        for mid in g["members"]:
            print(f"    - {mid}")
        print(
            f"    -> review for overlap; keep the strongest, archive or "
            f"merge the rest (/library:promote + manual consolidation)"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Embedding-based near-duplicate clustering over memories."
    )
    parser.add_argument("library", nargs="?", default=None, help="Library root.")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"Cosine similarity threshold (default: {DEFAULT_THRESHOLD}).")
    parser.add_argument("--min-cluster", type=int, default=5,
                        help="Tag-clustering fallback minimum cluster size.")
    parser.add_argument("--json", action="store_true", help="Emit groups as JSON.")
    args = parser.parse_args(argv)

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    jsonl_path = library / embed_memory.JSONL_REL
    records = embed_memory.load_jsonl(jsonl_path)

    if not records:
        print(
            "note: no embeddings artifact found — falling back to stdlib "
            "tag-based clustering. Run `embed_memory.py --backfill` to enable "
            "embedding near-duplicate detection.",
            file=sys.stderr,
        )
        report = library_cluster.cluster(library, min_cluster=args.min_cluster)
        library_cluster.print_report(report, min_cluster=args.min_cluster, library=library)
        return 0

    groups = near_duplicate_groups(records, threshold=args.threshold)

    if args.json:
        print(json.dumps(groups, separators=(",", ":")))
        return 0

    _print_report(groups, threshold=args.threshold, library=library)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
