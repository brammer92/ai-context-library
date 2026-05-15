"""Tests for scripts.library_cluster_embed — embedding near-duplicate clustering.

Fully deterministic: tests build embeddings/memories.jsonl with hand-chosen
vectors, so the cosine grouping is exactly predictable. No backend.
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

import library_cluster_embed as lce  # noqa: E402


def write_jsonl(lib: Path, records: list[dict]) -> None:
    p = lib / "embeddings" / "memories.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n", encoding="utf-8")


def rec(rid: str, vec: list[float], tags=None) -> dict:
    return {"id": rid, "type": "decision", "tags": tags or ["t"], "vector": vec}


def run(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = lce.main(args)
    return rc, out.getvalue(), err.getvalue()


class TestNearDuplicateGroups(unittest.TestCase):
    def test_identical_vectors_group_together(self):
        records = {
            "mem_a": rec("mem_a", [1.0, 0.0, 0.0]),
            "mem_b": rec("mem_b", [1.0, 0.0, 0.0]),   # identical to a
            "mem_c": rec("mem_c", [0.0, 1.0, 0.0]),   # orthogonal
        }
        groups = lce.near_duplicate_groups(records, threshold=0.92)
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]["members"]), {"mem_a", "mem_b"})

    def test_threshold_excludes_weak_pairs(self):
        # ~0.7 cosine — below a 0.92 threshold, above a 0.5 one.
        records = {
            "mem_a": rec("mem_a", [1.0, 0.0]),
            "mem_b": rec("mem_b", [1.0, 1.0]),
        }
        self.assertEqual(lce.near_duplicate_groups(records, threshold=0.92), [])
        self.assertEqual(len(lce.near_duplicate_groups(records, threshold=0.5)), 1)

    def test_transitive_chain_merges_into_one_group(self):
        # a~b and b~c (both strong) -> a,b,c in one group even if a/c weaker.
        records = {
            "mem_a": rec("mem_a", [1.0, 0.05, 0.0]),
            "mem_b": rec("mem_b", [1.0, 0.0, 0.0]),
            "mem_c": rec("mem_c", [1.0, 0.0, 0.05]),
        }
        groups = lce.near_duplicate_groups(records, threshold=0.95)
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]["members"]), {"mem_a", "mem_b", "mem_c"})

    def test_singletons_are_not_groups(self):
        records = {
            "mem_a": rec("mem_a", [1.0, 0.0]),
            "mem_b": rec("mem_b", [0.0, 1.0]),
        }
        self.assertEqual(lce.near_duplicate_groups(records, threshold=0.92), [])

    def test_group_reports_max_similarity(self):
        records = {
            "mem_a": rec("mem_a", [1.0, 0.0]),
            "mem_b": rec("mem_b", [1.0, 0.0]),
        }
        groups = lce.near_duplicate_groups(records, threshold=0.9)
        self.assertAlmostEqual(groups[0]["max_cos"], 1.0, places=6)


class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reports_near_duplicate_group(self):
        write_jsonl(self.lib, [
            rec("mem_dup1", [1.0, 0.0, 0.0], ["docker"]),
            rec("mem_dup2", [1.0, 0.0, 0.0], ["docker"]),
            rec("mem_uniq", [0.0, 0.0, 1.0], ["vlan"]),
        ])
        rc, out, err = run([str(self.lib)])
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("mem_dup1", out)
        self.assertIn("mem_dup2", out)
        self.assertNotIn("mem_uniq", out)

    def test_no_embeddings_falls_back_to_tag_clustering(self):
        # No embeddings/ file at all: must not crash, must note the fallback.
        (self.lib / "memories" / "decisions").mkdir(parents=True)
        rc, out, err = run([str(self.lib)])
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("tag", (out + err).lower())  # mentions the tag-clustering fallback

    def test_clean_corpus_reports_none(self):
        write_jsonl(self.lib, [
            rec("mem_a", [1.0, 0.0, 0.0]),
            rec("mem_b", [0.0, 1.0, 0.0]),
            rec("mem_c", [0.0, 0.0, 1.0]),
        ])
        rc, out, err = run([str(self.lib)])
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("none", out.lower())

    def test_json_output_parseable(self):
        write_jsonl(self.lib, [
            rec("mem_a", [1.0, 0.0]),
            rec("mem_b", [1.0, 0.0]),
        ])
        rc, out, err = run([str(self.lib), "--json"])
        self.assertEqual(rc, 0, msg=err)
        payload = json.loads(out)
        self.assertEqual(len(payload), 1)
        self.assertEqual(set(payload[0]["members"]), {"mem_a", "mem_b"})

    def test_library_not_found_exits_2(self):
        rc, _, err = run(["/no/such/lib/zzz"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
