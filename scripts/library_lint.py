#!/usr/bin/env python3
"""Lint the AI context library — merged Karpathy lint + Hermes retrospective.

Checks:
    - Schema integrity: every memory, skill, and bounded file validates.
    - Stale claims: memories with updated_at > --stale-days days old.
    - Orphan memories: memory ids not referenced by any other file.
    - Cross-reference gaps: skill bodies mentioning a mem_* id where the
      memory doesn't reference the skill back.
    - Cap pressure: MEMORY.md / USER.md / CONSTRAINTS.md over 80% (warning)
      or 95% (finding) of cap.
    - Tag distribution: top 10 tags by memory count.
    - Recent activity: memories whose created_at is within --recent-days.
    - Recommendations: actionable next-step suggestions.

Exit codes:
    0  clean (warnings only)
    1  findings (hard issues)
    2  bad invocation
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import common
import validate_bounded
import validate_memory
import validate_skill


MEM_ID_RE = re.compile(r"\bmem_[a-z0-9_]+\b")
SKILL_ID_RE = re.compile(r"\bskill_[a-z0-9_]+\b")


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


def _load_skills(library: Path) -> list[tuple[Path, dict, str]]:
    out: list[tuple[Path, dict, str]] = []
    sk_root = library / "skills"
    if not sk_root.is_dir():
        return out
    for sub in sk_root.iterdir():
        if not sub.is_dir():
            continue
        skill_md = sub / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
            meta, body = common.parse_frontmatter(text)
        except (OSError, ValueError):
            continue
        out.append((skill_md, meta, body))
    return out


def lint(library: Path, *, now: datetime | None = None, stale_days: int = 90, recent_days: int = 7) -> dict:
    now = now or datetime.now(timezone.utc)
    report: dict = {
        "schema_failures": [],
        "stale": [],
        "orphans": [],
        "xref_gaps": [],
        "cap_warnings": [],
        "cap_findings": [],
        "top_tags": [],
        "recent_memories": [],
        "recommendations": [],
    }

    memories = _load_memories(library)
    skills = _load_skills(library)

    # Schema integrity.
    for path, _meta, _body in memories:
        errs = validate_memory.validate(path)
        if errs:
            report["schema_failures"].append((str(path.relative_to(library)), errs[:3]))
    for path, _meta, _body in skills:
        errs = validate_skill.validate(path)
        if errs:
            report["schema_failures"].append((str(path.relative_to(library)), errs[:3]))
    for name in common.HERMES_CAPS:
        p = library / name
        if p.is_file():
            errs = validate_bounded.validate(p)
            if errs:
                report["schema_failures"].append((name, errs[:3]))

    # Stale claims.
    stale_threshold = now - timedelta(days=stale_days)
    for path, meta, _body in memories:
        ts = meta.get("updated_at", "")
        if not isinstance(ts, str) or not common.is_iso8601(ts):
            continue
        try:
            updated = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if updated < stale_threshold:
            report["stale"].append((str(path.relative_to(library)), ts))

    # Orphan + cross-reference analysis.
    all_text_blobs: list[tuple[str, str]] = []  # (origin label, text)
    for path, _meta, body in memories:
        all_text_blobs.append((str(path.relative_to(library)), body))
    for path, _meta, body in skills:
        all_text_blobs.append((str(path.relative_to(library)), body))
    for name in ("MEMORY.md", "USER.md", "CONSTRAINTS.md", "AGENTS.md", "CLAUDE.md", "CHATGPT.md"):
        p = library / name
        if p.is_file():
            try:
                _m, b = common.parse_frontmatter(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                b = ""
            all_text_blobs.append((name, b))

    referenced_mem_ids: set[str] = set()
    referenced_skill_ids: set[str] = set()
    mem_ids_by_origin: dict[str, set[str]] = {}
    for origin, text in all_text_blobs:
        ids = set(MEM_ID_RE.findall(text))
        mem_ids_by_origin[origin] = ids
        referenced_mem_ids.update(ids)
        referenced_skill_ids.update(SKILL_ID_RE.findall(text))

    for path, meta, body in memories:
        mid = meta.get("id", "")
        if not isinstance(mid, str) or not mid:
            continue
        self_origin = str(path.relative_to(library))
        # Word-boundary matched references across all blobs except self.
        appearances = sum(
            1
            for origin, ids in mem_ids_by_origin.items()
            if origin != self_origin and mid in ids
        )
        if appearances == 0:
            report["orphans"].append((self_origin, mid))

    # Cross-reference gaps: skill mentions mem_X but memory doesn't mention skill back.
    for sk_path, sk_meta, sk_body in skills:
        sid = sk_meta.get("id", "")
        mentioned = MEM_ID_RE.findall(sk_body)
        for mid in set(mentioned):
            mem_path = None
            mem_body = None
            for mp, mm, mb in memories:
                if mm.get("id") == mid:
                    mem_path, mem_body = mp, mb
                    break
            if mem_path is None:
                continue
            if isinstance(sid, str) and sid and sid not in mem_body:
                report["xref_gaps"].append(
                    (str(sk_path.relative_to(library)), str(mem_path.relative_to(library)), sid, mid)
                )

    # Cap pressure.
    for name, cap in common.HERMES_CAPS.items():
        p = library / name
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        body_len = common.body_char_count(text)
        pct = (body_len / cap) * 100
        if pct >= 95:
            report["cap_findings"].append((name, body_len, cap, round(pct, 1)))
        elif pct >= 80:
            report["cap_warnings"].append((name, body_len, cap, round(pct, 1)))

    # Tag distribution.
    counter: Counter[str] = Counter()
    for _path, meta, _body in memories:
        tags = meta.get("tags") or []
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, str):
                    counter[tag] += 1
    report["top_tags"] = counter.most_common(10)

    # Recent activity.
    recent_threshold = now - timedelta(days=recent_days)
    for path, meta, _body in memories:
        ts = meta.get("created_at", "")
        if not isinstance(ts, str) or not common.is_iso8601(ts):
            continue
        try:
            created = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if created >= recent_threshold:
            report["recent_memories"].append((str(path.relative_to(library)), ts))

    # Recommendations.
    recs: list[str] = []
    for name, body_len, cap, pct in report["cap_findings"]:
        recs.append(f"{name} at {pct}% of cap ({body_len}/{cap}) — run /library:consolidate")
    for name, body_len, cap, pct in report["cap_warnings"]:
        recs.append(f"{name} at {pct}% of cap — consider /library:consolidate soon")
    if report["stale"]:
        recs.append(f"{len(report['stale'])} memory file(s) > {stale_days} days stale — review or remove")
    if report["orphans"]:
        recs.append(f"{len(report['orphans'])} orphan memory id(s) — promote into MEMORY.md or link from a skill")
    if report["xref_gaps"]:
        recs.append(f"{len(report['xref_gaps'])} skill→memory cross-reference gap(s)")
    for tag, count in report["top_tags"]:
        if count >= 5:
            recs.append(f"tag '{tag}' appears in {count} memories — consider /library:cluster")
    report["recommendations"] = recs

    return report


def print_report(report: dict, *, library: Path) -> None:
    print(f"AI Context Library — lint report ({library})")
    print("=" * 60)

    if report["schema_failures"]:
        print(f"\nSchema failures ({len(report['schema_failures'])}):")
        for path, errs in report["schema_failures"]:
            print(f"  - {path}")
            for e in errs:
                print(f"      · {e}")
    else:
        print("\nSchema: OK")

    if report["cap_findings"] or report["cap_warnings"]:
        print(f"\nCap pressure:")
        for name, body_len, cap, pct in report["cap_findings"]:
            print(f"  ! {name}: {body_len}/{cap} ({pct}%) — over 95% cap")
        for name, body_len, cap, pct in report["cap_warnings"]:
            print(f"  ~ {name}: {body_len}/{cap} ({pct}%) — over 80% cap")
    else:
        print("\nCap pressure: OK")

    if report["stale"]:
        print(f"\nStale memories ({len(report['stale'])}):")
        for path, ts in report["stale"]:
            print(f"  - {path} (updated_at {ts})")
    if report["orphans"]:
        print(f"\nOrphan memories ({len(report['orphans'])}):")
        for path, mid in report["orphans"]:
            print(f"  - {path} ({mid})")
    if report["xref_gaps"]:
        print(f"\nCross-reference gaps ({len(report['xref_gaps'])}):")
        for sk_path, mem_path, sid, mid in report["xref_gaps"]:
            print(f"  - {sk_path} mentions {mid}, but {mem_path} does not mention {sid}")

    if report["top_tags"]:
        print(f"\nTop tags:")
        for tag, count in report["top_tags"]:
            print(f"  {tag}: {count}")

    if report["recent_memories"]:
        print(f"\nRecent activity ({len(report['recent_memories'])}):")
        for path, ts in report["recent_memories"][:10]:
            print(f"  - {path} ({ts})")

    if report["recommendations"]:
        print(f"\nRecommendations:")
        for r in report["recommendations"]:
            print(f"  → {r}")
    else:
        print("\nRecommendations: none — library is healthy.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint the AI context library.")
    parser.add_argument("library", nargs="?", default=None, help="Library root.")
    parser.add_argument("--stale-days", type=int, default=90)
    parser.add_argument("--recent-days", type=int, default=7)
    args = parser.parse_args(argv)

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = lint(library, stale_days=args.stale_days, recent_days=args.recent_days)
    print_report(report, library=library)

    hard_issues = (
        bool(report["schema_failures"])
        or bool(report["cap_findings"])
        or bool(report["stale"])
        or bool(report["xref_gaps"])
    )
    return 1 if hard_issues else 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
