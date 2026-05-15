#!/usr/bin/env python3
"""Contradiction candidate detection for a draft memory.

Two layers, with very different confidence levels:

  1. CANDIDATE NARROWING (deterministic, high-confidence). Embed the
     draft, find its nearest neighbours, and band them by cosine:
       cos >= --high  -> "likely"   contradiction candidate
       --low..--high  -> "possible" contradiction candidate
     This alone is useful: "here are the existing memories most likely
     to conflict — eyeball them." Pure math, fully tested, no backend.

  2. JUDGE (LLM-as-judge, pluggable, lower-confidence). An injectable
     `judge_fn(draft, neighbour) -> verdict` classifies each candidate
     pair as agrees / unrelated / contradicts / supersedes. The default
     judge is `_anthropic_judge` (Haiku-tier), used ONLY when
     `--judge` is passed and ANTHROPIC_API_KEY is set. If no judge is
     wired, or it fails, every verdict is reported "UNAVAILABLE" — an
     honest non-answer, never a fabricated "no contradiction".

The narrowing does its job at high confidence; the judge's *accuracy*
needs a live API smoke test before it should be trusted — see PR_BODY.md.

Usage:
    python scripts/library_contradict.py --text "draft body" [--judge]
    python scripts/library_contradict.py --memory mem_x [--json]

Exit codes:
    0  success, or a graceful skip (Ollama down)
    2  bad invocation, or library path not found
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import common
import embed_memory
import embed_query
from embed_load_clickhouse import DEFAULT_CLICKHOUSE_URL, DEFAULT_TABLE
from embed_memory import OllamaUnavailable

DEFAULT_HIGH = 0.92
DEFAULT_LOW = 0.82
VERDICTS = {"agrees", "unrelated", "contradicts", "supersedes"}
DEFAULT_JUDGE_MODEL = os.environ.get("LIBRARY_JUDGE_MODEL", "claude-haiku-4-5-20251001")


class JudgeUnavailable(RuntimeError):
    """Raised when the LLM judge cannot be reached or used.

    Always caught and turned into an "UNAVAILABLE" verdict — the judge
    is an enhancement, never a gate.
    """


def find_candidates(neighbours: list[dict], *, high: float, low: float) -> list[dict]:
    """Band neighbours into contradiction candidates by cosine similarity.

    Returns a cosine-desc-sorted list of candidates (cos >= low), each
    with a `band` of "likely" (>= high) or "possible" (low..high).
    """
    out: list[dict] = []
    for n in neighbours:
        cos = float(n.get("cos", 0.0))
        if cos < low:
            continue
        out.append({
            "id": n.get("id", ""),
            "type": n.get("type", ""),
            "tags": n.get("tags", []) or [],
            "cos": round(cos, 6),
            "band": "likely" if cos >= high else "possible",
        })
    out.sort(key=lambda c: c["cos"], reverse=True)
    return out


def judge_candidates(
    candidates: list[dict], draft_text: str, neighbour_texts: dict[str, str], *, judge_fn,
) -> list[dict]:
    """Attach a `verdict` to each candidate.

    With no judge_fn, or on any JudgeUnavailable, the verdict is
    "UNAVAILABLE" — an explicit non-answer. Never fabricates a verdict.
    """
    for c in candidates:
        if judge_fn is None:
            c["verdict"] = "UNAVAILABLE"
            continue
        try:
            verdict = judge_fn(draft_text, neighbour_texts.get(c["id"], ""))
        except JudgeUnavailable:
            verdict = "UNAVAILABLE"
        c["verdict"] = verdict if verdict in VERDICTS else str(verdict)
    return candidates


def _anthropic_judge(draft: str, neighbour: str, *, key: str, model: str) -> str:
    """Haiku-tier LLM-as-judge over one (draft, neighbour) pair. Stdlib only.

    Raises JudgeUnavailable on a missing key, network failure, or an
    unparseable response.
    """
    if not key:
        raise JudgeUnavailable("ANTHROPIC_API_KEY is not set")
    prompt = (
        "You compare two knowledge-base memories. Reply with EXACTLY one "
        "word: agrees, unrelated, contradicts, or supersedes.\n\n"
        f"DRAFT MEMORY:\n{draft}\n\nEXISTING MEMORY:\n{neighbour}\n\n"
        "One word:"
    )
    body = json.dumps({
        "model": model,
        "max_tokens": 8,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = payload["content"][0]["text"].strip().lower()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError,
            json.JSONDecodeError, KeyError, IndexError) as exc:
        raise JudgeUnavailable(f"Anthropic judge failed: {exc}") from exc
    for v in VERDICTS:
        if v in text:
            return v
    raise JudgeUnavailable(f"judge returned an unrecognised verdict: {text!r}")


def _load_memory_bodies(library: Path, ids: set[str]) -> dict[str, str]:
    bodies: dict[str, str] = {}
    mem_root = library / "memories"
    if not mem_root.is_dir():
        return bodies
    for path in mem_root.rglob("*.md"):
        try:
            meta, body = common.parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        mid = meta.get("id")
        if mid in ids:
            bodies[mid] = body
    return bodies


def main(argv: list[str] | None = None, *, embed_fn=None, judge_fn=None) -> int:
    parser = argparse.ArgumentParser(
        description="Surface contradiction candidates for a draft memory."
    )
    parser.add_argument("--text", default=None, help="Draft memory text to check.")
    parser.add_argument("--memory", default=None,
                        help="Existing memory id; its body becomes the query (and is excluded).")
    parser.add_argument("--library", default=None,
                        help="Library root. Defaults to $AI_CONTEXT_LIBRARY_PATH or cwd.")
    parser.add_argument("--k", type=int, default=5, help="Neighbours to consider.")
    parser.add_argument("--high", type=float, default=DEFAULT_HIGH,
                        help=f"'likely' candidate cosine threshold (default: {DEFAULT_HIGH}).")
    parser.add_argument("--low", type=float, default=DEFAULT_LOW,
                        help=f"'possible' candidate cosine threshold (default: {DEFAULT_LOW}).")
    parser.add_argument("--judge", action="store_true",
                        help="Run the Anthropic LLM judge (needs ANTHROPIC_API_KEY).")
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--clickhouse-url", default=DEFAULT_CLICKHOUSE_URL)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--ollama-host", default=embed_memory.DEFAULT_OLLAMA_HOST)
    parser.add_argument("--model", default=embed_memory.DEFAULT_MODEL)
    parser.add_argument("--json", action="store_true", help="Emit candidates as JSON.")
    args = parser.parse_args(argv)

    if bool(args.text) == bool(args.memory):
        print("error: pass exactly one of --text or --memory.", file=sys.stderr)
        return 2

    try:
        library = common.resolve_library_path(args.library)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    exclude_id = None
    if args.memory:
        bodies = _load_memory_bodies(library, {args.memory})
        if args.memory not in bodies:
            print(f"error: memory '{args.memory}' not found under memories/.", file=sys.stderr)
            return 2
        query_text = bodies[args.memory]
        exclude_id = args.memory
    else:
        query_text = args.text

    if embed_fn is None:
        def embed_fn(text: str) -> list[float]:  # noqa: E306
            return embed_memory._ollama_embed(text, model=args.model, host=args.ollama_host)

    # Default judge: only wire the real one when explicitly asked AND a key exists.
    if judge_fn is None and args.judge:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

        def judge_fn(draft: str, neighbour: str) -> str:  # noqa: E306
            return _anthropic_judge(draft, neighbour, key=anthropic_key, model=args.judge_model)

    try:
        vector = embed_fn(query_text)
    except OllamaUnavailable as exc:
        print(
            f"note: contradiction check unavailable — {exc}. The caller should "
            f"treat the contradiction field as UNAVAILABLE and proceed.",
            file=sys.stderr,
        )
        if args.json:
            print("[]")
        return 0

    hits, source = embed_query.nearest(
        vector, library, k=args.k, exclude_id=exclude_id,
        clickhouse_url=args.clickhouse_url, table=args.table,
    )
    candidates = find_candidates(hits, high=args.high, low=args.low)
    neighbour_texts = _load_memory_bodies(library, {c["id"] for c in candidates})
    candidates = judge_candidates(candidates, query_text, neighbour_texts, judge_fn=judge_fn)

    if args.json:
        print(json.dumps(candidates, separators=(",", ":")))
        return 0

    if source == "local":
        print("note: ClickHouse unavailable; used the local JSONL cosine fallback.",
              file=sys.stderr)

    if not candidates:
        print("contradiction candidates: none "
              f"(no existing memory within cosine {args.low} of the draft).")
        return 0

    print(f"contradiction candidates ({len(candidates)}):")
    for c in candidates:
        print(f"  [{c['band']}]  cos {c['cos']:.3f}  {c['id']}  verdict: {c['verdict']}")
    if any(c["verdict"] == "UNAVAILABLE" for c in candidates):
        print("\nnote: verdicts are UNAVAILABLE — run with --judge (and "
              "ANTHROPIC_API_KEY set) for an LLM verdict, or eyeball the "
              "candidates above for a genuine conflict.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
