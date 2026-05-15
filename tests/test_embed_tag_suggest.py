"""Tests for scripts.embed_tag_suggest — auto-tag assist.

Deterministic: tag suggestion is frequency ranking over a neighbour set.
Tests inject a fake embed_fn; the neighbour lookup is brute-force cosine
over a JSONL we write directly.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import embed_tag_suggest as ets  # noqa: E402



def neighbour(tags: list[str]) -> dict:
    return {"id": "mem_x", "type": "decision", "tags": tags, "cos": 0.9}


def write_jsonl(lib: Path, records: list[dict]) -> None:
    p = lib / "embeddings" / "memories.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n", encoding="utf-8")


def run(args: list[str], embed_fn) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = ets.main(args, embed_fn=embed_fn)
    return rc, out.getvalue(), err.getvalue()


class TestSuggestTags(unittest.TestCase):
    def test_ranks_by_frequency(self):
        neighbours = [
            neighbour(["docker", "security"]),
            neighbour(["docker", "networking"]),
            neighbour(["docker"]),
        ]
        sug = ets.suggest_tags(neighbours, existing_tags=[], max_suggestions=5, min_count=1)
        self.assertEqual(sug[0]["tag"], "docker")
        self.assertEqual(sug[0]["count"], 3)

    def test_excludes_existing_tags(self):
        neighbours = [neighbour(["docker", "security"]), neighbour(["docker"])]
        sug = ets.suggest_tags(neighbours, existing_tags=["docker"], max_suggestions=5, min_count=1)
        self.assertNotIn("docker", [s["tag"] for s in sug])
        self.assertIn("security", [s["tag"] for s in sug])

    def test_respects_min_count(self):
        neighbours = [neighbour(["docker", "rare"]), neighbour(["docker"])]
        sug = ets.suggest_tags(neighbours, existing_tags=[], max_suggestions=5, min_count=2)
        self.assertEqual([s["tag"] for s in sug], ["docker"])

    def test_skips_non_kebab_tags(self):
        neighbours = [neighbour(["Good_Tag", "valid-tag"]), neighbour(["valid-tag"])]
        sug = ets.suggest_tags(neighbours, existing_tags=[], max_suggestions=5, min_count=1)
        self.assertEqual([s["tag"] for s in sug], ["valid-tag"])

    def test_caps_at_max(self):
        neighbours = [neighbour(["a", "b", "c", "d", "e"])]
        sug = ets.suggest_tags(neighbours, existing_tags=[], max_suggestions=2, min_count=1)
        self.assertEqual(len(sug), 2)

    def test_empty_neighbours_yields_nothing(self):
        self.assertEqual(ets.suggest_tags([], existing_tags=[], max_suggestions=5, min_count=1), [])


class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_suggests_from_neighbours(self):
        write_jsonl(self.lib, [
            {"id": "mem_a", "type": "decision", "tags": ["docker", "security"], "vector": [1.0, 0.0]},
            {"id": "mem_b", "type": "decision", "tags": ["docker"], "vector": [0.99, 0.01]},
            {"id": "mem_c", "type": "fact", "tags": ["unrelated"], "vector": [0.0, 1.0]},
        ])
        embed_fn = lambda t: [1.0, 0.0]  # noqa: E731
        rc, out, err = run(
            ["--text", "a docker deployment decision", "--library", str(self.lib), "--k", "2"],
            embed_fn,
        )
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("docker", out)

    def test_ollama_down_is_graceful(self):
        write_jsonl(self.lib, [
            {"id": "mem_a", "type": "decision", "tags": ["docker"], "vector": [1.0]},
        ])
        import embed_memory

        def boom(text: str):
            raise embed_memory.OllamaUnavailable("down (test)")

        rc, out, err = run(
            ["--text", "anything", "--library", str(self.lib)],
            boom,
        )
        self.assertEqual(rc, 0, msg="Ollama down must not fail the caller")
        self.assertIn("unavailable", (out + err).lower())

    def test_json_output_parseable(self):
        write_jsonl(self.lib, [
            {"id": "mem_a", "type": "decision", "tags": ["docker", "security"], "vector": [1.0, 0.0]},
            {"id": "mem_b", "type": "decision", "tags": ["docker"], "vector": [1.0, 0.0]},
        ])
        embed_fn = lambda t: [1.0, 0.0]  # noqa: E731
        rc, out, err = run(
            ["--text", "docker thing", "--library", str(self.lib), "--json"],
            embed_fn,
        )
        self.assertEqual(rc, 0, msg=err)
        payload = json.loads(out)
        self.assertEqual(payload[0]["tag"], "docker")

    def test_requires_text(self):
        rc, _, err = run(["--library", str(self.lib)], lambda t: [1.0])
        self.assertEqual(rc, 2)

    def test_library_not_found_exits_2(self):
        rc, _, err = run(["--text", "x", "--library", "/no/such/lib/zzz"], lambda t: [1.0])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
