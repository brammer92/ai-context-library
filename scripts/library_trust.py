#!/usr/bin/env python3
"""Deterministic trust scoring for memories — the Hermes-flavoured signal.

Trust is NOT a model. It is a transparent, auditable weighted formula
over signals already in the repo:

    trust = clamp(0, 1,
        BASE
      + importance prior        (critical/high/medium/low)
      + reference bonus         (how many other files cite this memory)
      + promotion bonus         (is the id present in MEMORY.md?)
      - age decay               (days since updated_at)
    )

A transparent formula beats a black box for a single-user signal: the
user can read every weight below and adjust it. Trust is advisory — it
is never a gate.

The score is written to two frontmatter fields, `trust` and
`trust_updated_at`, so all three agents (Claude Code, Claude web,
ChatGPT) read it for free from the same Markdown they already read.

Default mode is DRY-RUN: it prints what it would set and changes
nothing. `--apply` writes the frontmatter — and even then the human
still gates the result, because the change shows up in `git diff` and
goes through `/library:review` + `/library:commit` like any other write.

Usage:
    python scripts/library_trust.py [--library PATH]            # dry-run
    python scripts/library_trust.py --library PATH --apply      # write

Exit codes:
    0  success
    2  bad invocation, or library path not found
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import common

# --- Tunable weights. Edit these; the formula is intentionally legible. ---
BASE = 0.50
IMPORTANCE_BONUS = {"low": 0.00, "medium": 0.05, "high": 0.10, "critical": 0.15}
REFERENCE_BONUS_PER = 0.05      # per other file that cites the memory id
REFERENCE_BONUS_CAP = 3        # ... counted up to this many references
PROMOTION_BONUS = 0.15          # id appears in MEMORY.md working set
AGE_DECAY_MAX = 0.20            # full decay after AGE_DECAY_FULL_DAYS
AGE_DECAY_FULL_DAYS = 365

MEM_ID_RE = re.compile(r"\bmem_[a-z0-9_]+\b")


def compute_trust(meta: dict, *, ref_count: int, promoted: bool,
                  now: datetime | None = None) -> float:
    """Return a deterministic trust score in [0, 1] for one memory."""
    now = now or datetime.now(timezone.utc)
    score = BASE
    score += IMPORTANCE_BONUS.get(str(meta.get("importance", "medium")), 0.0)
    score += min(max(ref_count, 0), REFERENCE_BONUS_CAP) * REFERENCE_BONUS_PER
    if promoted:
        score += PROMOTION_BONUS

    updated = meta.get("updated_at", "")
    if isinstance(updated, str) and common.is_iso8601(updated):
        try:
            dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            age_days = max((now - dt).total_seconds() / 86400.0, 0.0)
            score -= min(age_days / AGE_DECAY_FULL_DAYS, 1.0) * AGE_DECAY_MAX
        except (ValueError, TypeError):
            pass

    return round(min(max(score, 0.0), 1.0), 3)


def _load_memories(library: Path) -> list[tuple[Path, dict, str]]:
    out: list[tuple[Path, dict, str]] = []
    mem_root = library / "memories"
    if not mem_root.is_dir():
        return out
    for path in sorted(mem_root.rglob("*.md")):
        try:
            meta, body = common.parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append((path, meta, body))
    return out


def _collect_signal_text(library: Path, memories: list[tuple[Path, dict, str]]) -> dict[str, str]:
    """Return {origin: text} for every file that might cite a memory id."""
    blobs: dict[str, str] = {}
    for path, _meta, body in memories:
        blobs[str(path.relative_to(library))] = body
    for name in ("MEMORY.md", "USER.md", "CONSTRAINTS.md",
                 "AGENTS.md", "CLAUDE.md", "CHATGPT.md"):
        p = library / name
        if p.is_file():
            try:
                _m, b = common.parse_frontmatter(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                b = ""
            blobs[name] = b
    sk_root = library / "skills"
    if sk_root.is_dir():
        for sub in sorted(sk_root.iterdir()):
            skill_md = sub / "SKILL.md"
            if skill_md.is_file():
                try:
                    blobs[str(skill_md.relative_to(library))] = skill_md.read_text(encoding="utf-8")
                except OSError:
                    pass
    ctx_root = library / "context"
    if ctx_root.is_dir():
        for p in sorted(ctx_root.glob("*.md")):
            try:
                blobs[str(p.relative_to(library))] = p.read_text(encoding="utf-8")
            except OSError:
                pass
    return blobs


def score_library(library: Path, *, now: datetime | None = None) -> list[dict]:
    """Score every memory. Returns a deterministic, id-sorted list of dicts."""
    now = now or datetime.now(timezone.utc)
    memories = _load_memories(library)
    blobs = _collect_signal_text(library, memories)

    ids_by_origin: dict[str, set[str]] = {
        origin: set(MEM_ID_RE.findall(text)) for origin, text in blobs.items()
    }
    promoted_ids = ids_by_origin.get("MEMORY.md", set())

    results: list[dict] = []
    for path, meta, _body in memories:
        mid = meta.get("id", "")
        if not isinstance(mid, str) or not mid:
            continue
        self_origin = str(path.relative_to(library))
        ref_count = sum(
            1 for origin, ids in ids_by_origin.items()
            if origin != self_origin and mid in ids
        )
        promoted = mid in promoted_ids
        new_trust = compute_trust(meta, ref_count=ref_count, promoted=promoted, now=now)
        old_trust = meta.get("trust")
        try:
            old_trust = float(old_trust) if old_trust is not None else None
        except (ValueError, TypeError):
            old_trust = None
        results.append({
            "id": mid,
            "path": self_origin,
            "ref_count": ref_count,
            "promoted": promoted,
            "old_trust": old_trust,
            "new_trust": new_trust,
        })
    results.sort(key=lambda r: r["id"])
    return results


def apply_scores(library: Path, results: list[dict], *, now: datetime | None = None) -> int:
    """Write `trust` / `trust_updated_at` frontmatter. Returns files changed."""
    ts = common.now_iso() if now is None else now.strftime("%Y-%m-%dT%H:%M:%SZ")
    changed = 0
    for r in results:
        path = library / r["path"]
        try:
            meta, body = common.parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        meta["trust"] = r["new_trust"]
        meta["trust_updated_at"] = ts
        path.write_text(common.dump_frontmatter(meta, body), encoding="utf-8")
        changed += 1
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic trust scoring for memories.")
    parser.add_argument("--library", default=None,
                        help="Library root. Defaults to $AI_CONTEXT_LIBRARY_PATH or cwd.")
    parser.add_argument("--apply", action="store_true",
                        help="Write trust frontmatter. Default is dry-run.")
    parser.add_argument("--json", action="store_true", help="Emit scores as JSON.")
    args = parser.parse_args(argv)

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    results = score_library(library)

    if args.json:
        print(json.dumps(results, separators=(",", ":")))
        if args.apply:
            apply_scores(library, results)
        return 0

    print(f"AI Context Library — trust scoring ({library})")
    print("=" * 60)
    if not results:
        print("\nNo memories to score.")
        return 0
    for r in results:
        delta = ""
        if r["old_trust"] is not None and r["old_trust"] != r["new_trust"]:
            delta = f"  (was {r['old_trust']})"
        flags = []
        if r["promoted"]:
            flags.append("promoted")
        if r["ref_count"]:
            flags.append(f"{r['ref_count']} ref(s)")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        print(f"  {r['new_trust']:.3f}  {r['id']}{suffix}{delta}")

    if args.apply:
        changed = apply_scores(library, results)
        print(f"\napplied: wrote trust frontmatter to {changed} memory file(s).")
        print("next: review with /library:review, then /library:commit.")
    else:
        print(f"\ndry-run: {len(results)} memory file(s) would be updated. "
              f"Re-run with --apply to write (the commit is still yours to make).")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
