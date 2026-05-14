#!/usr/bin/env python3
"""Generate embeddings for memory files into the embeddings/ sidecar.

This is the write-time half of the embeddings layer. It reads memory
Markdown files, asks Ollama for a vector, and upserts one JSON line per
memory into ``<library>/embeddings/memories.jsonl`` — the canonical,
git-tracked embedding artifact.

Design constraints honoured here:
  - Stdlib only. The Ollama call is a plain ``urllib`` POST; this script
    is NOT on the validator import path but is kept dependency-free
    anyway for consistency with the rest of scripts/.
  - Graceful degradation. If Ollama is unreachable the script prints a
    warning and exits 0 without touching the JSONL — the memory write
    and the rest of the pipeline are unaffected.
  - Hash-based freshness. Each line carries a content_hash over the
    memory body + type + tags. An unchanged memory is never re-embedded,
    so the JSONL stays byte-stable across re-runs.

Usage:
    python scripts/embed_memory.py --backfill [--library PATH]
    python scripts/embed_memory.py <memory-file.md> [--library PATH]

Exit codes:
    0  success, or a graceful skip (Ollama down, non-memory path)
    2  bad invocation, or library path not found
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import common


DEFAULT_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("LIBRARY_EMBED_MODEL", "nomic-embed-text")
JSONL_REL = "embeddings/memories.jsonl"


class OllamaUnavailable(RuntimeError):
    """Raised when the embedding backend cannot be reached or used.

    Always caught by ``main`` and turned into a graceful skip — it must
    never propagate out of the script and break the write pipeline.
    """


# --------------------------------------------------------------------------
# Content hashing — the freshness primitive.
# --------------------------------------------------------------------------
def content_hash(meta: dict, body: str) -> str:
    """Return ``sha256:<hex>`` over the semantically meaningful content.

    Only the memory ``type``, its ``tags`` (order-independent), and the
    body affect the hash. Frontmatter churn that does not change meaning
    (updated_at, importance, source, ...) leaves the hash stable, so an
    edit that only touches those fields does not trigger a re-embed.
    """
    mtype = str(meta.get("type", ""))
    tags = meta.get("tags", []) or []
    norm_tags = ",".join(sorted(str(t) for t in tags))
    payload = f"{mtype}\n{norm_tags}\n{body.strip()}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _embed_input(meta: dict, body: str) -> str:
    """Text actually sent to the embedder: title gives the vector context."""
    title = str(meta.get("title", "")).strip()
    return f"{title}\n\n{body.strip()}".strip()


# --------------------------------------------------------------------------
# JSONL store — the canonical artifact.
# --------------------------------------------------------------------------
def load_jsonl(path: Path) -> dict[str, dict]:
    """Load embeddings/memories.jsonl into an id -> record dict.

    A missing file yields an empty dict. Malformed lines are skipped
    rather than raising — a corrupt line should not break a write.
    """
    if not path.exists():
        return {}
    records: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = rec.get("id")
        if rid:
            records[rid] = rec
    return records


def write_jsonl(path: Path, records: dict[str, dict]) -> None:
    """Write records as JSONL, one line per memory, sorted by id.

    Sorting + compact separators make the file deterministic: the same
    set of records always produces byte-identical output, so git diffs
    show exactly which memories changed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for rid in sorted(records):
        lines.append(json.dumps(records[rid], separators=(",", ":"), sort_keys=True))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


# --------------------------------------------------------------------------
# Ollama backend.
# --------------------------------------------------------------------------
def _ollama_embed(text: str, *, model: str, host: str) -> list[float]:
    """POST to Ollama's /api/embeddings endpoint. Stdlib-only.

    Raises OllamaUnavailable on any connection, HTTP, or response-shape
    problem so the caller can degrade gracefully.
    """
    url = host.rstrip("/") + "/api/embeddings"
    data = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as exc:
        raise OllamaUnavailable(f"Ollama request failed: {exc}") from exc
    vector = payload.get("embedding")
    if not isinstance(vector, list) or not vector:
        raise OllamaUnavailable(f"Ollama returned no embedding for model '{model}'")
    return [float(x) for x in vector]


# --------------------------------------------------------------------------
# Core processing.
# --------------------------------------------------------------------------
def _memory_files(library: Path) -> list[Path]:
    memories_dir = library / "memories"
    if not memories_dir.is_dir():
        return []
    return sorted(p for p in memories_dir.rglob("*.md") if p.is_file())


def _is_memory_path(library: Path, path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(library.resolve())
    except ValueError:
        return False
    return rel.parts[:1] == ("memories",) and path.suffix == ".md"


def process(
    library: Path,
    targets: list[Path],
    *,
    embed_fn,
    model: str,
    prune: bool,
) -> tuple[int, int, int]:
    """Embed each target memory file, upserting into the JSONL store.

    Returns (embedded, unchanged, skipped). The JSONL is only rewritten
    when something actually changed, so a no-op run leaves the file
    byte-identical (and a fully-skipped run leaves it untouched, even
    absent).
    """
    jsonl_path = library / JSONL_REL
    records = load_jsonl(jsonl_path)

    embedded = unchanged = skipped = 0
    changed = False

    for path in targets:
        if not path.exists():
            continue
        try:
            meta, body = common.parse_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            skipped += 1
            continue
        mem_id = meta.get("id")
        if not mem_id:
            skipped += 1
            continue

        chash = content_hash(meta, body)
        existing = records.get(mem_id)
        if existing and existing.get("content_hash") == chash:
            unchanged += 1
            continue

        try:
            vector = embed_fn(_embed_input(meta, body))
        except OllamaUnavailable as exc:
            print(f"warning: skipped {mem_id} — {exc}", file=sys.stderr)
            skipped += 1
            continue

        records[mem_id] = {
            "id": mem_id,
            "content_hash": chash,
            "model": model,
            "dim": len(vector),
            "embedded_at": common.now_iso(),
            "type": meta.get("type", ""),
            "tags": meta.get("tags", []) or [],
            "vector": vector,
        }
        embedded += 1
        changed = True

    if prune:
        live_ids = set()
        for path in _memory_files(library):
            try:
                meta, _ = common.parse_frontmatter(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if meta.get("id"):
                live_ids.add(meta["id"])
        stale = [rid for rid in records if rid not in live_ids]
        for rid in stale:
            del records[rid]
            changed = True
        if stale:
            print(f"pruned {len(stale)} embedding(s) for deleted memories", file=sys.stderr)

    if changed:
        write_jsonl(jsonl_path, records)

    return embedded, unchanged, skipped


def main(argv: list[str] | None = None, *, embed_fn=None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate memory embeddings into the embeddings/ sidecar."
    )
    parser.add_argument("path", nargs="?", default=None,
                        help="A single memory file to embed. Mutually exclusive with --backfill.")
    parser.add_argument("--backfill", action="store_true",
                        help="Embed every memory under <library>/memories/.")
    parser.add_argument("--library", default=None,
                        help="Library root. Defaults to $AI_CONTEXT_LIBRARY_PATH or cwd.")
    parser.add_argument("--ollama-host", default=DEFAULT_OLLAMA_HOST,
                        help=f"Ollama base URL (default: {DEFAULT_OLLAMA_HOST}).")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Embedding model (default: {DEFAULT_MODEL}).")
    parser.add_argument("--force", action="store_true",
                        help="Re-embed even if the content hash is unchanged.")
    args = parser.parse_args(argv)

    if bool(args.path) == bool(args.backfill):
        print("error: pass exactly one of <path> or --backfill.", file=sys.stderr)
        return 2

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if embed_fn is None:
        def embed_fn(text: str) -> list[float]:  # noqa: E306
            return _ollama_embed(text, model=args.model, host=args.ollama_host)

    if args.backfill:
        targets = _memory_files(library)
        prune = True
    else:
        path = Path(args.path)
        if not _is_memory_path(library, path):
            print(f"note: {args.path} is not a memory file under memories/ — nothing to embed.")
            return 0
        targets = [path]
        prune = False

    if args.force:
        # Drop matching records so the hash check always misses.
        jsonl_path = library / JSONL_REL
        records = load_jsonl(jsonl_path)
        target_ids = set()
        for path in targets:
            try:
                meta, _ = common.parse_frontmatter(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if meta.get("id"):
                target_ids.add(meta["id"])
        if target_ids & set(records):
            for rid in target_ids:
                records.pop(rid, None)
            write_jsonl(jsonl_path, records)

    embedded, unchanged, skipped = process(
        library, targets, embed_fn=embed_fn, model=args.model, prune=prune,
    )

    print(f"embedded: {embedded}  unchanged: {unchanged}  skipped: {skipped}")
    if skipped:
        print(
            "note: skipped memories were not embedded (Ollama unreachable or "
            "unparseable) — the JSONL and the rest of the pipeline are unaffected.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
