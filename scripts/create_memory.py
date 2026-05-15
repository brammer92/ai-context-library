#!/usr/bin/env python3
"""Generate a structured memory file under the AI context library.

Writes the candidate to a tempfile outside the library tree first, runs
validation and the secret scanner against the tempfile, and only moves
it into place via os.replace() once both pass. A failure at either gate
unlinks the tempfile; nothing fails-but-lands in the library tree, so a
directory-watching backup/sync can never capture content that didn't
clear both checks.

Exit codes:
    0  success (file created and validated)
    1  validation or secret-scan failure
    2  bad invocation
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import common
import scan_secrets
import validate_memory


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _title_from_content(content: str) -> str:
    """Take first 6 words as title."""
    words = content.strip().split()
    if not words:
        return "Untitled"
    return " ".join(words[:6]).rstrip(".,;:!?")


def _has_secret_pattern(text: str) -> tuple[bool, str | None]:
    """Pre-scan combined title+content for credential-shaped tokens.

    Reuses scan_secrets.PATTERNS and the env-var-ref suppression rules so
    the in-process pre-check and the post-write file scan stay in sync.
    Prevents a slug derived from a secret from briefly hitting disk.
    """
    for name, regex in scan_secrets.PATTERNS:
        m = regex.search(text)
        if not m:
            continue
        if name in scan_secrets._ENV_VAR_REF_SUPPRESSED:
            value = m.groupdict().get("value") or ""
            if scan_secrets._ENV_VAR_REF_RE.match(value):
                continue
        return True, name
    return False, None


def build_memory(
    *,
    content: str,
    mtype: str,
    title: str | None,
    scope: str,
    agent_scope: list[str],
    tags: list[str],
    importance: str,
    source: str,
    now: datetime | None = None,
) -> tuple[dict, str, str]:
    """Return (frontmatter_dict, body, target_relative_path)."""
    if now is None:
        now = datetime.now(timezone.utc)
    ts = common.now_iso() if now is None else now.strftime("%Y-%m-%dT%H:%M:%SZ")
    actual_title = (title or _title_from_content(content)).strip()
    mem_id = common.generate_memory_id(actual_title, now)
    folder = common.MEMORY_TYPE_TO_FOLDER[mtype]
    body = f"# {actual_title}\n\n{content.strip()}\n"
    meta = {
        "id": mem_id,
        "title": actual_title,
        "type": mtype,
        "scope": scope,
        "agent_scope": agent_scope,
        "tags": tags,
        "importance": importance,
        "created_at": ts,
        "updated_at": ts,
        "source": source,
    }
    rel = f"{folder}/{mem_id}.md"
    return meta, body, rel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a memory file.")
    parser.add_argument("--content", required=True, help="Memory content (durable, specific).")
    parser.add_argument("--title", default=None, help="Optional title; derived from content if absent.")
    parser.add_argument("--type", dest="mtype", required=True, choices=sorted(common.MEMORY_TYPES))
    parser.add_argument("--scope", default="global", choices=sorted(common.MEMORY_SCOPES))
    parser.add_argument("--agent-scope", default=None, help="Comma-separated. Defaults to '*' or $AI_CONTEXT_LIBRARY_DEFAULT_AGENT_SCOPE.")
    parser.add_argument("--tags", default="", help="Comma-separated kebab-case tags.")
    parser.add_argument("--importance", default="medium", choices=sorted(common.IMPORTANCE_VALUES))
    parser.add_argument("--source", default=None, help="Defaults to 'claude-code' or $AI_CONTEXT_LIBRARY_DEFAULT_SOURCE.")
    parser.add_argument("--library", default=None, help="Library root. Defaults to $AI_CONTEXT_LIBRARY_PATH or cwd.")
    parser.add_argument("--force", action="store_true", help="Overwrite if target file exists.")
    parser.add_argument("--dry-run", action="store_true", help="Print the would-be file content and exit.")
    args = parser.parse_args(argv)

    combined = f"{args.title or ''}\n{args.content or ''}"
    found, pattern = _has_secret_pattern(combined)
    if found:
        print(
            f"error: refusing to write memory - content contains a "
            f"credential-shaped token (pattern: {pattern}). Remove or "
            f"redact before retrying.",
            file=sys.stderr,
        )
        return 1

    agent_scope_csv = args.agent_scope or os.environ.get("AI_CONTEXT_LIBRARY_DEFAULT_AGENT_SCOPE") or "*"
    agent_scope = _split_csv(agent_scope_csv) or ["*"]
    tags = _split_csv(args.tags)
    source = args.source or os.environ.get("AI_CONTEXT_LIBRARY_DEFAULT_SOURCE") or "claude-code"

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    meta, body, rel = build_memory(
        content=args.content,
        mtype=args.mtype,
        title=args.title,
        scope=args.scope,
        agent_scope=agent_scope,
        tags=tags,
        importance=args.importance,
        source=source,
    )

    serialized = common.dump_frontmatter(meta, body)

    if args.dry_run:
        print(f"# would write to: {library / rel}\n")
        print(serialized)
        return 0

    target = library / rel
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and not args.force:
        print(f"error: refusing to overwrite existing file: {target}", file=sys.stderr)
        return 1

    # Write to a tempfile OUTSIDE the library tree so directory-watching
    # syncs never see content that fails validation or the secret scan.
    # NamedTemporaryFile defaults to $TMPDIR / /tmp.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8",
    ) as tmp:
        tmp.write(serialized)
        tmp_path: Path | None = Path(tmp.name)

    try:
        val_errors = validate_memory.validate(tmp_path)
        if val_errors:
            print(f"INVALID generated memory (rejected before write):", file=sys.stderr)
            for e in val_errors:
                print(f"  - {e}", file=sys.stderr)
            return 1

        if scan_secrets.main([str(tmp_path)]) != 0:
            print(
                f"error: secret findings in generated memory; not writing to {target}",
                file=sys.stderr,
            )
            return 1

        # Both gates passed — move into place atomically.
        os.replace(tmp_path, target)
        tmp_path = None  # ownership transferred to target
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

    print(f"created: {target}")
    print("next: review changes with /library:review, then commit with /library:commit")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
