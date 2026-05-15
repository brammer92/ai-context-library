"""Tests for scripts.embed_memory.

No live embedding backend is contacted in tests: every test injects a
fake ``embed_fn``. The graceful-degradation path is exercised with a
fake that raises ``EmbedUnavailable``.
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
import embed_memory  # noqa: E402


def fake_embed(text: str) -> list[float]:
    """Deterministic 4-dim 'embedding' derived from the text length."""
    n = float(len(text))
    return [n, n / 2.0, n / 3.0, n / 4.0]


def unavailable_embed(text: str) -> list[float]:
    raise embed_memory.EmbedUnavailable("connection refused (test)")


def write_memory(lib: Path, folder: str, mem_id: str, *, body: str,
                 mtype: str = "decision", tags: list[str] | None = None) -> Path:
    tags = tags if tags is not None else ["alpha", "beta"]
    meta = {
        "id": mem_id,
        "title": mem_id.replace("_", " "),
        "type": mtype,
        "scope": "project",
        "agent_scope": ["*"],
        "tags": tags,
        "importance": "medium",
        "created_at": "2026-05-14T00:00:00Z",
        "updated_at": "2026-05-14T00:00:00Z",
        "source": "claude-code",
    }
    path = lib / "memories" / folder / f"{mem_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(common.dump_frontmatter(meta, f"# {mem_id}\n\n{body}\n"), encoding="utf-8")
    return path


def run(args: list[str], embed_fn=fake_embed) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = embed_memory.main(args, embed_fn=embed_fn)
    return rc, out.getvalue(), err.getvalue()


class TestContentHash(unittest.TestCase):
    def test_is_deterministic_and_prefixed(self):
        meta = {"type": "decision", "tags": ["b", "a"]}
        h1 = embed_memory.content_hash(meta, "the body text")
        h2 = embed_memory.content_hash(meta, "the body text")
        self.assertEqual(h1, h2)
        self.assertTrue(h1.startswith("sha256:"))

    def test_changes_with_body(self):
        meta = {"type": "decision", "tags": ["a"]}
        self.assertNotEqual(
            embed_memory.content_hash(meta, "body one"),
            embed_memory.content_hash(meta, "body two"),
        )

    def test_changes_with_type_and_tags(self):
        base = embed_memory.content_hash({"type": "decision", "tags": ["a"]}, "body")
        self.assertNotEqual(base, embed_memory.content_hash({"type": "fact", "tags": ["a"]}, "body"))
        self.assertNotEqual(base, embed_memory.content_hash({"type": "decision", "tags": ["a", "b"]}, "body"))

    def test_tag_order_does_not_matter(self):
        self.assertEqual(
            embed_memory.content_hash({"type": "decision", "tags": ["a", "b"]}, "body"),
            embed_memory.content_hash({"type": "decision", "tags": ["b", "a"]}, "body"),
        )

    def test_ignores_frontmatter_noise(self):
        """updated_at / importance churn must not change the content hash."""
        a = embed_memory.content_hash(
            {"type": "decision", "tags": ["a"], "updated_at": "2026-01-01T00:00:00Z"}, "body")
        b = embed_memory.content_hash(
            {"type": "decision", "tags": ["a"], "updated_at": "2099-12-31T00:00:00Z"}, "body")
        self.assertEqual(a, b)


class TestJsonlStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "embeddings" / "memories.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_returns_empty(self):
        self.assertEqual(embed_memory.load_jsonl(self.path), {})

    def test_upsert_adds_then_replaces(self):
        records = embed_memory.load_jsonl(self.path)
        records["mem_b"] = {"id": "mem_b", "content_hash": "sha256:1"}
        embed_memory.write_jsonl(self.path, records)
        records = embed_memory.load_jsonl(self.path)
        records["mem_b"] = {"id": "mem_b", "content_hash": "sha256:2"}
        embed_memory.write_jsonl(self.path, records)
        lines = self.path.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["content_hash"], "sha256:2")

    def test_write_is_sorted_by_id(self):
        records = {
            "mem_c": {"id": "mem_c"},
            "mem_a": {"id": "mem_a"},
            "mem_b": {"id": "mem_b"},
        }
        embed_memory.write_jsonl(self.path, records)
        ids = [json.loads(l)["id"] for l in self.path.read_text().splitlines()]
        self.assertEqual(ids, ["mem_a", "mem_b", "mem_c"])


class TestBackfill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)
        self.jsonl = self.lib / "embeddings" / "memories.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_backfill_embeds_all_memories(self):
        write_memory(self.lib, "decisions", "mem_20260514_one", body="First durable decision body.")
        write_memory(self.lib, "facts", "mem_20260514_two", body="Second durable fact body.", mtype="fact")
        rc, out, err = run(["--backfill", "--library", str(self.lib)])
        self.assertEqual(rc, 0, msg=err)
        records = embed_memory.load_jsonl(self.jsonl)
        self.assertEqual(set(records), {"mem_20260514_one", "mem_20260514_two"})
        for rec in records.values():
            self.assertEqual(rec["dim"], 4)
            self.assertEqual(len(rec["vector"]), 4)
            self.assertTrue(rec["content_hash"].startswith("sha256:"))
        self.assertIn("embedded: 2", out)

    def test_unchanged_memory_not_reembedded(self):
        write_memory(self.lib, "decisions", "mem_20260514_one", body="A durable decision body here.")
        run(["--backfill", "--library", str(self.lib)])
        first = embed_memory.load_jsonl(self.jsonl)["mem_20260514_one"]["embedded_at"]
        rc, out, err = run(["--backfill", "--library", str(self.lib)])
        self.assertEqual(rc, 0, msg=err)
        second = embed_memory.load_jsonl(self.jsonl)["mem_20260514_one"]["embedded_at"]
        self.assertEqual(first, second)
        self.assertIn("unchanged: 1", out)

    def test_changed_body_triggers_reembed(self):
        path = write_memory(self.lib, "decisions", "mem_20260514_one", body="Original decision body text.")
        run(["--backfill", "--library", str(self.lib)])
        h1 = embed_memory.load_jsonl(self.jsonl)["mem_20260514_one"]["content_hash"]
        meta, _ = common.parse_frontmatter(path.read_text())
        path.write_text(common.dump_frontmatter(meta, "# x\n\nCompletely rewritten decision body.\n"), encoding="utf-8")
        rc, out, _ = run(["--backfill", "--library", str(self.lib)])
        self.assertEqual(rc, 0)
        h2 = embed_memory.load_jsonl(self.jsonl)["mem_20260514_one"]["content_hash"]
        self.assertNotEqual(h1, h2)
        self.assertIn("embedded: 1", out)

    def test_single_file_mode(self):
        path = write_memory(self.lib, "decisions", "mem_20260514_solo", body="A single durable decision.")
        rc, out, err = run([str(path), "--library", str(self.lib)])
        self.assertEqual(rc, 0, msg=err)
        self.assertEqual(set(embed_memory.load_jsonl(self.jsonl)), {"mem_20260514_solo"})

    def test_model_mismatch_triggers_reembed(self):
        """Changing the embedding model re-embeds every record, even those
        whose content_hash is otherwise unchanged — so a backend swap
        auto-migrates the corpus on the next backfill."""
        write_memory(self.lib, "decisions", "mem_20260514_one",
                     body="A durable decision body about networking.")
        rc, _, _ = run(["--backfill", "--library", str(self.lib), "--model", "model-a"])
        self.assertEqual(rc, 0)
        self.assertEqual(embed_memory.load_jsonl(self.jsonl)["mem_20260514_one"]["model"], "model-a")
        rc, out, _ = run(["--backfill", "--library", str(self.lib), "--model", "model-b"])
        self.assertEqual(rc, 0)
        self.assertIn("embedded: 1", out)  # not "unchanged: 1"
        self.assertEqual(embed_memory.load_jsonl(self.jsonl)["mem_20260514_one"]["model"], "model-b")

    def test_single_file_outside_memories_is_ignored(self):
        other = self.lib / "context" / "note.md"
        other.parent.mkdir(parents=True)
        other.write_text("not a memory\n", encoding="utf-8")
        rc, out, err = run([str(other), "--library", str(self.lib)])
        self.assertEqual(rc, 0, msg=err)
        self.assertFalse(self.jsonl.exists())


class TestGracefulDegradation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)
        self.jsonl = self.lib / "embeddings" / "memories.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_ollama_unavailable_exits_zero_and_writes_nothing(self):
        write_memory(self.lib, "decisions", "mem_20260514_one", body="A durable decision body.")
        rc, out, err = run(["--backfill", "--library", str(self.lib)], embed_fn=unavailable_embed)
        self.assertEqual(rc, 0, msg="must not break the pipeline when the embedder is down")
        self.assertFalse(self.jsonl.exists())
        self.assertIn("skipped", (out + err).lower())

    def test_ollama_unavailable_preserves_existing_jsonl(self):
        write_memory(self.lib, "decisions", "mem_20260514_one", body="A durable decision body.")
        run(["--backfill", "--library", str(self.lib)])  # good run
        before = self.jsonl.read_text()
        write_memory(self.lib, "facts", "mem_20260514_two", body="A second durable fact.", mtype="fact")
        rc, _, _ = run(["--backfill", "--library", str(self.lib)], embed_fn=unavailable_embed)
        self.assertEqual(rc, 0)
        self.assertEqual(self.jsonl.read_text(), before)

    def test_library_not_found_exits_2(self):
        rc, _, err = run(["--backfill", "--library", "/no/such/library/zzz"])
        self.assertEqual(rc, 2)
        self.assertIn("error", err.lower())

    def test_requires_path_or_backfill(self):
        rc, _, err = run(["--library", str(self.lib)])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
