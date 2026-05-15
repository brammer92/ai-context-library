#!/usr/bin/env python3
"""Load the embeddings/memories.jsonl artifact into ClickHouse.

This is the query-cache half of the embeddings layer. ClickHouse holds
``library_embeddings`` so /library:cluster and the dedup/contradiction
skills can run fast cosine-distance queries. It is strictly a CACHE:

  - The canonical artifact is embeddings/memories.jsonl in the git repo.
  - This table is rebuildable from that file at any time
    (``embed_load_clickhouse.py --library PATH``).
  - If ClickHouse is unreachable the loader prints a warning and exits 0
    — nothing on the write path depends on it.

Stdlib only. The ClickHouse call is a plain ``urllib`` POST to the HTTP
interface using ``INSERT ... FORMAT JSONEachRow``.

Usage:
    python scripts/embed_load_clickhouse.py [--library PATH]
    python scripts/embed_load_clickhouse.py --from-jsonl PATH --only mem_x

Exit codes:
    0  success, or a graceful skip (ClickHouse down, no JSONL)
    2  bad invocation, or library path not found
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import common
import embed_memory


DEFAULT_CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "http://localhost:8123")
DEFAULT_TABLE = os.environ.get("LIBRARY_CLICKHOUSE_TABLE", "library_embeddings")
JSONL_REL = embed_memory.JSONL_REL


class ClickHouseUnavailable(RuntimeError):
    """Raised when ClickHouse cannot be reached or rejects the insert.

    Always caught by ``main`` and turned into a graceful skip — the
    table is a cache, never a dependency.
    """


def to_clickhouse_row(record: dict) -> dict:
    """Map a memories.jsonl record onto the library_embeddings columns.

    The only real transform is ``embedded_at``: the JSONL stores
    ISO-8601 with a Z suffix (canonical, cross-agent readable) while
    ClickHouse DateTime wants 'YYYY-MM-DD HH:MM:SS'.
    """
    embedded_at = str(record.get("embedded_at", ""))
    try:
        dt = datetime.fromisoformat(embedded_at.replace("Z", "+00:00"))
        embedded_at = dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        pass  # leave as-is; ClickHouse best-effort parsing or a later fix
    return {
        "id": record.get("id", ""),
        "content_hash": record.get("content_hash", ""),
        "model": record.get("model", ""),
        "dim": int(record.get("dim", 0) or 0),
        "vector": [float(x) for x in record.get("vector", [])],
        "embedded_at": embedded_at,
        "type": record.get("type", ""),
        "tags": list(record.get("tags", []) or []),
    }


def build_insert_payload(records: dict[str, dict]) -> str:
    """Render records as JSONEachRow, one JSON object per line, sorted by id."""
    lines = [
        json.dumps(to_clickhouse_row(records[rid]), separators=(",", ":"), sort_keys=True)
        for rid in sorted(records)
    ]
    return "\n".join(lines)


def _clickhouse_insert(payload: str, *, url: str, table: str) -> None:
    """POST a JSONEachRow batch to ClickHouse's HTTP interface.

    Raises ClickHouseUnavailable on any connection or HTTP failure.
    """
    query = f"INSERT INTO {table} FORMAT JSONEachRow"
    full_url = url.rstrip("/") + "/?" + urllib.parse.urlencode({"query": query})
    req = urllib.request.Request(
        full_url, data=payload.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise ClickHouseUnavailable(f"ClickHouse insert failed: {exc}") from exc


def main(argv: list[str] | None = None, *, insert_fn=None) -> int:
    parser = argparse.ArgumentParser(
        description="Load embeddings/memories.jsonl into the ClickHouse query cache."
    )
    parser.add_argument("--library", default=None,
                        help="Library root. Defaults to $AI_CONTEXT_LIBRARY_PATH or cwd.")
    parser.add_argument("--from-jsonl", default=None,
                        help="Path to the JSONL artifact (default: <library>/embeddings/memories.jsonl).")
    parser.add_argument("--only", default=None,
                        help="Load just this memory id (used by the post-write hook).")
    parser.add_argument("--clickhouse-url", default=DEFAULT_CLICKHOUSE_URL,
                        help=f"ClickHouse HTTP base URL (default: {DEFAULT_CLICKHOUSE_URL}).")
    parser.add_argument("--table", default=DEFAULT_TABLE,
                        help=f"Target table (default: {DEFAULT_TABLE}).")
    args = parser.parse_args(argv)

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    jsonl_path = Path(args.from_jsonl) if args.from_jsonl else library / JSONL_REL
    if not jsonl_path.exists():
        print(f"note: no embeddings artifact at {jsonl_path} — nothing to load.")
        return 0

    records = embed_memory.load_jsonl(jsonl_path)
    if args.only:
        records = {k: v for k, v in records.items() if k == args.only}
    if not records:
        print("note: no records to load.")
        return 0

    if insert_fn is None:
        def insert_fn(payload: str) -> None:  # noqa: E306
            _clickhouse_insert(payload, url=args.clickhouse_url, table=args.table)

    payload = build_insert_payload(records)
    try:
        insert_fn(payload)
    except ClickHouseUnavailable as exc:
        print(
            f"warning: ClickHouse cache not updated — {exc}. "
            f"The canonical artifact {jsonl_path} is unaffected; rerun this "
            f"loader once ClickHouse is reachable.",
            file=sys.stderr,
        )
        return 0

    print(f"loaded {len(records)} embedding row(s) into {args.table}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
