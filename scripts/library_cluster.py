#!/usr/bin/env python3
"""Detect tag clusters across memories and propose skills or consolidations.

Merged Hermes "detect-patterns" + "consolidate" command. Output is
suggestion-only — nothing is mutated.

Usage:
    python scripts/library_cluster.py [<library>] [--min-cluster 5]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

import common


# Tags that hint a cluster is a procedure (extract a skill) rather than a
# fact (extract a consolidation).
PROCEDURE_TAGS = {
    "review", "audit", "checklist", "workflow", "procedure",
    "playbook", "runbook", "template",
}


def _load_memories(library: Path) -> list[tuple[Path, dict, str]]:
    out: list[tuple[Path, dict, str]] = []
    mem_root = library / "memories"
    if not mem_root.is_dir():
        return out
    for path in mem_root.rglob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
            meta, body = common.parse_frontmatter(text)
        except (OSError, ValueError):
            continue
        out.append((path, meta, body))
    return out


def cluster(library: Path, *, min_cluster: int = 5) -> dict:
    memories = _load_memories(library)
    tag_counter: Counter[str] = Counter()
    tag_members: dict[str, list[Path]] = {}
    pair_counter: Counter[tuple[str, str]] = Counter()
    pair_members: dict[tuple[str, str], list[Path]] = {}

    for path, meta, _body in memories:
        tags = meta.get("tags") or []
        if not isinstance(tags, list):
            continue
        clean = sorted({t for t in tags if isinstance(t, str)})
        for tag in clean:
            tag_counter[tag] += 1
            tag_members.setdefault(tag, []).append(path)
        for a, b in combinations(clean, 2):
            pair_counter[(a, b)] += 1
            pair_members.setdefault((a, b), []).append(path)

    single_clusters: list[tuple[str, int, list[Path]]] = []
    for tag, count in tag_counter.most_common():
        if count >= min_cluster:
            single_clusters.append((tag, count, tag_members[tag]))

    pair_clusters: list[tuple[tuple[str, str], int, list[Path]]] = []
    for pair, count in pair_counter.most_common():
        if count >= min_cluster:
            pair_clusters.append((pair, count, pair_members[pair]))

    proposals: list[str] = []
    for tag, _count, _members in single_clusters:
        if tag in PROCEDURE_TAGS:
            proposals.append(
                f"skill: /library:add-skill '{tag.title()} Procedure' "
                f"--tags {tag},procedure (extracted from {_count} memories)"
            )
        else:
            proposals.append(
                f"consolidate: review {_count} memories tagged '{tag}' "
                f"for overlap (use /library:promote for the strongest, "
                f"archive the rest)"
            )
    for (a, b), count, members in pair_clusters:
        if any(t in PROCEDURE_TAGS for t in (a, b)):
            proposals.append(
                f"skill: /library:add-skill '{a.title()} {b.title()}' "
                f"--tags {a},{b} (extracted from {count} co-occurring memories)"
            )
        else:
            proposals.append(
                f"consolidate: {count} memories share tags '{a}'+'{b}'; "
                f"consider merging into one memory"
            )

    return {
        "single_clusters": single_clusters,
        "pair_clusters": pair_clusters,
        "proposals": proposals,
    }


def print_report(report: dict, *, min_cluster: int, library: Path) -> None:
    print(f"AI Context Library — cluster report ({library})")
    print(f"Minimum cluster size: {min_cluster}")
    print("=" * 60)

    if report["single_clusters"]:
        print("\nSingle-tag clusters:")
        for tag, count, members in report["single_clusters"]:
            print(f"  {tag} ({count} memories):")
            for m in members[:5]:
                print(f"    - {m.relative_to(library)}")
            if len(members) > 5:
                print(f"    ... and {len(members) - 5} more")
    else:
        print("\nSingle-tag clusters: none above threshold")

    if report["pair_clusters"]:
        print("\nTag-pair clusters:")
        for (a, b), count, members in report["pair_clusters"]:
            print(f"  {a}+{b} ({count} memories)")
    else:
        print("\nTag-pair clusters: none above threshold")

    if report["proposals"]:
        print("\nProposals:")
        for p in report["proposals"]:
            print(f"  → {p}")
    else:
        print("\nProposals: none")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find tag clusters across memories.")
    parser.add_argument("library", nargs="?", default=None)
    parser.add_argument("--min-cluster", type=int, default=5)
    args = parser.parse_args(argv)

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = cluster(library, min_cluster=args.min_cluster)
    print_report(report, min_cluster=args.min_cluster, library=library)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
