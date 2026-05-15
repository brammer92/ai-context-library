"""Tests for scripts.embed_query — nearest-neighbour lookup.

No live backend: tests inject a fake ``embed_fn`` and exercise the local
brute-force cosine over embeddings/memories.jsonl directly.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import common  # noqa: E402
import embed_query  # noqa: E402


def fake_embed_factory(table: dict[str, list[float]]):
    """Return an embed_fn that maps known text to fixed vectors."""
    def _embed(text: str) -> list[float]:
        for key, vec in table.items():
            if key in text:
                return vec
        return [0.0, 0.0, 0.0]
    return _embed


def write_jsonl(lib: Path, records: list[dict]) -> None:
    p = lib / "embeddings" / "memories.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n", encoding="utf-8")


def write_memory(lib: Path, mem_id: str, body: str) -> Path:
    meta = {
        "id": mem_id, "title": mem_id, "type": "decision", "scope": "project",
        "agent_scope": ["*"], "tags": ["t"], "importance": "medium",
        "created_at": "2026-05-14T00:00:00Z", "updated_at": "2026-05-14T00:00:00Z",
        "source": "claude-code",
    }
    p = lib / "memories" / "decisions" / f"{mem_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(common.dump_frontmatter(meta, f"# {mem_id}\n\n{body}\n"), encoding="utf-8")
    return p


def run(args: list[str], embed_fn) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = embed_query.main(args, embed_fn=embed_fn)
    return rc, out.getvalue(), err.getvalue()


class TestCosine(unittest.TestCase):
    def test_identical_vectors_score_one(self):
        self.assertAlmostEqual(embed_query.cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), 1.0, places=6)

    def test_orthogonal_vectors_score_zero(self):
        self.assertAlmostEqual(embed_query.cosine([1.0, 0.0], [0.0, 1.0]), 0.0, places=6)

    def test_zero_vector_is_safe(self):
        self.assertEqual(embed_query.cosine([0.0, 0.0], [1.0, 1.0]), 0.0)


class TestLocalQuery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)
        write_jsonl(self.lib, [
            {"id": "mem_near", "type": "decision", "tags": ["a"], "vector": [1.0, 0.0, 0.0]},
            {"id": "mem_far", "type": "fact", "tags": ["b"], "vector": [0.0, 1.0, 0.0]},
            {"id": "mem_self", "type": "decision", "tags": ["c"], "vector": [1.0, 1.0, 1.0]},
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_returns_topk_sorted_by_similarity(self):
        jsonl = self.lib / "embeddings" / "memories.jsonl"
        hits = embed_query.query_local_jsonl([1.0, 0.0, 0.0], jsonl, k=2, exclude_id=None)
        self.assertEqual(hits[0]["id"], "mem_near")
        self.assertAlmostEqual(hits[0]["cos"], 1.0, places=6)
        self.assertEqual(len(hits), 2)

    def test_excludes_self(self):
        jsonl = self.lib / "embeddings" / "memories.jsonl"
        hits = embed_query.query_local_jsonl([1.0, 1.0, 1.0], jsonl, k=5, exclude_id="mem_self")
        self.assertNotIn("mem_self", [h["id"] for h in hits])


class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_text_query_returns_neighbours(self):
        write_jsonl(self.lib, [
            {"id": "mem_docker", "type": "user_preference", "tags": ["docker"], "vector": [1.0, 0.0]},
            {"id": "mem_other", "type": "fact", "tags": ["x"], "vector": [0.0, 1.0]},
        ])
        embed_fn = fake_embed_factory({"compose": [1.0, 0.0]})
        rc, out, err = run(
            ["--text", "docker compose preference", "--library", str(self.lib)],
            embed_fn,
        )
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("mem_docker", out)

    def test_memory_id_query_excludes_itself(self):
        write_memory(self.lib, "mem_subject", "A durable decision about networking.")
        write_jsonl(self.lib, [
            {"id": "mem_subject", "type": "decision", "tags": ["net"], "vector": [1.0, 0.0]},
            {"id": "mem_neighbour", "type": "decision", "tags": ["net"], "vector": [0.9, 0.1]},
        ])
        embed_fn = fake_embed_factory({"networking": [1.0, 0.0]})
        rc, out, err = run(
            ["--memory", "mem_subject", "--library", str(self.lib)],
            embed_fn,
        )
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("mem_neighbour", out)
        self.assertNotIn("mem_subject", out)

    def test_no_embeddings_file_is_graceful(self):
        embed_fn = fake_embed_factory({"anything": [1.0]})
        rc, out, err = run(
            ["--text", "anything at all", "--library", str(self.lib)],
            embed_fn,
        )
        self.assertEqual(rc, 0)
        self.assertIn("no", (out + err).lower())  # "no neighbours"

    def test_json_output_is_parseable(self):
        write_jsonl(self.lib, [
            {"id": "mem_a", "type": "decision", "tags": ["a"], "vector": [1.0, 0.0]},
        ])
        embed_fn = fake_embed_factory({"query": [1.0, 0.0]})
        rc, out, err = run(
            ["--text", "query text", "--library", str(self.lib), "--json"],
            embed_fn,
        )
        self.assertEqual(rc, 0, msg=err)
        payload = json.loads(out)
        self.assertEqual(payload[0]["id"], "mem_a")

    def test_library_not_found_exits_2(self):
        embed_fn = fake_embed_factory({})
        rc, _, err = run(["--text", "x", "--library", "/no/such/lib/zzz"], embed_fn)
        self.assertEqual(rc, 2)

    def test_requires_text_or_memory(self):
        embed_fn = fake_embed_factory({})
        rc, _, err = run(["--library", str(self.lib)], embed_fn)
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
