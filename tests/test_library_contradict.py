"""Tests for scripts.library_contradict — contradiction candidate detection.

Two layers are tested separately:
  - find_candidates / band classification — deterministic cosine logic,
    the 95%-confident core.
  - judge orchestration — exercised with a stub judge_fn (and one that
    raises) so the graceful-degradation path is covered. The REAL
    Anthropic judge (_anthropic_judge) is never called here; judgment
    quality needs a live API smoke test.
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

import common  # noqa: E402
import library_contradict as lc  # noqa: E402



def nb(mem_id: str, cos: float) -> dict:
    return {"id": mem_id, "type": "decision", "tags": ["t"], "cos": cos}


def write_jsonl(lib: Path, records: list[dict]) -> None:
    p = lib / "embeddings" / "memories.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n", encoding="utf-8")


def write_memory(lib: Path, mem_id: str, body: str) -> None:
    meta = {
        "id": mem_id, "title": mem_id, "type": "decision", "scope": "project",
        "agent_scope": ["*"], "tags": ["t"], "importance": "medium",
        "created_at": "2026-05-14T00:00:00Z", "updated_at": "2026-05-14T00:00:00Z",
        "source": "claude-code",
    }
    p = lib / "memories" / "decisions" / f"{mem_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(common.dump_frontmatter(meta, f"# {mem_id}\n\n{body}\n"), encoding="utf-8")


def run(args, embed_fn, judge_fn=None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = lc.main(args, embed_fn=embed_fn, judge_fn=judge_fn)
    return rc, out.getvalue(), err.getvalue()


class TestFindCandidates(unittest.TestCase):
    def test_high_band_is_likely(self):
        cands = lc.find_candidates([nb("mem_a", 0.95)], high=0.92, low=0.82)
        self.assertEqual(cands[0]["band"], "likely")

    def test_mid_band_is_possible(self):
        cands = lc.find_candidates([nb("mem_a", 0.86)], high=0.92, low=0.82)
        self.assertEqual(cands[0]["band"], "possible")

    def test_low_similarity_excluded(self):
        self.assertEqual(lc.find_candidates([nb("mem_a", 0.40)], high=0.92, low=0.82), [])

    def test_sorted_by_cosine_desc(self):
        cands = lc.find_candidates(
            [nb("mem_lo", 0.83), nb("mem_hi", 0.99), nb("mem_mid", 0.90)],
            high=0.92, low=0.82,
        )
        self.assertEqual([c["id"] for c in cands], ["mem_hi", "mem_mid", "mem_lo"])


class TestJudgeOrchestration(unittest.TestCase):
    def test_no_judge_marks_unavailable(self):
        cands = [nb("mem_a", 0.95)]
        judged = lc.judge_candidates(cands, "draft", {"mem_a": "text"}, judge_fn=None)
        self.assertEqual(judged[0]["verdict"], "UNAVAILABLE")

    def test_stub_judge_verdicts_applied(self):
        cands = [dict(nb("mem_a", 0.95)), dict(nb("mem_b", 0.93))]
        verdicts = iter(["contradicts", "agrees"])
        judged = lc.judge_candidates(
            cands, "draft", {"mem_a": "x", "mem_b": "y"},
            judge_fn=lambda draft, neighbour: next(verdicts),
        )
        self.assertEqual(judged[0]["verdict"], "contradicts")
        self.assertEqual(judged[1]["verdict"], "agrees")

    def test_judge_failure_degrades_to_unavailable(self):
        def boom(draft, neighbour):
            raise lc.JudgeUnavailable("no api key (test)")

        judged = lc.judge_candidates([nb("mem_a", 0.95)], "draft", {"mem_a": "x"}, judge_fn=boom)
        self.assertEqual(judged[0]["verdict"], "UNAVAILABLE")


class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_surfaces_candidates_from_local_fallback(self):
        write_memory(self.lib, "mem_existing", "Macvlan keeps source IPs intact for syslog.")
        write_jsonl(self.lib, [
            {"id": "mem_existing", "type": "decision", "tags": ["vlan"], "vector": [1.0, 0.0]},
            {"id": "mem_far", "type": "fact", "tags": ["x"], "vector": [0.0, 1.0]},
        ])
        rc, out, err = run(
            ["--text", "we dropped macvlan for syslog", "--library", str(self.lib)],
            embed_fn=lambda t: [1.0, 0.0],
        )
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("mem_existing", out)
        self.assertNotIn("mem_far", out)
        self.assertIn("UNAVAILABLE", out)  # no judge wired -> honest verdict

    def test_stub_judge_verdict_shown(self):
        write_memory(self.lib, "mem_existing", "Macvlan keeps source IPs intact.")
        write_jsonl(self.lib, [
            {"id": "mem_existing", "type": "decision", "tags": ["vlan"], "vector": [1.0, 0.0]},
        ])
        rc, out, err = run(
            ["--text", "dropped macvlan", "--library", str(self.lib)],
            embed_fn=lambda t: [1.0, 0.0],
            judge_fn=lambda draft, neighbour: "contradicts",
        )
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("contradicts", out)

    def test_no_candidates_when_corpus_dissimilar(self):
        write_jsonl(self.lib, [
            {"id": "mem_far", "type": "fact", "tags": ["x"], "vector": [0.0, 1.0]},
        ])
        rc, out, err = run(
            ["--text", "unrelated text", "--library", str(self.lib)],
            embed_fn=lambda t: [1.0, 0.0],
        )
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("none", out.lower())

    def test_ollama_down_is_graceful(self):
        import embed_memory
        write_jsonl(self.lib, [{"id": "mem_a", "type": "decision", "tags": ["t"], "vector": [1.0]}])

        def boom(text):
            raise embed_memory.OllamaUnavailable("down (test)")

        rc, out, err = run(
            ["--text", "x", "--library", str(self.lib)], boom,
        )
        self.assertEqual(rc, 0)
        self.assertIn("unavailable", (out + err).lower())

    def test_json_output_parseable(self):
        write_memory(self.lib, "mem_existing", "Macvlan keeps source IPs intact.")
        write_jsonl(self.lib, [
            {"id": "mem_existing", "type": "decision", "tags": ["vlan"], "vector": [1.0, 0.0]},
        ])
        rc, out, err = run(
            ["--text", "macvlan dropped", "--library", str(self.lib), "--json"],
            embed_fn=lambda t: [1.0, 0.0],
        )
        self.assertEqual(rc, 0, msg=err)
        payload = json.loads(out)
        self.assertEqual(payload[0]["id"], "mem_existing")
        self.assertIn("verdict", payload[0])

    def test_memory_mode_excludes_self(self):
        write_memory(self.lib, "mem_subject", "A networking decision.")
        write_memory(self.lib, "mem_other", "Another networking decision.")
        write_jsonl(self.lib, [
            {"id": "mem_subject", "type": "decision", "tags": ["net"], "vector": [1.0, 0.0]},
            {"id": "mem_other", "type": "decision", "tags": ["net"], "vector": [1.0, 0.0]},
        ])
        rc, out, err = run(
            ["--memory", "mem_subject", "--library", str(self.lib)],
            embed_fn=lambda t: [1.0, 0.0],
        )
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("mem_other", out)
        self.assertNotIn("mem_subject", out)

    def test_requires_text_or_memory(self):
        rc, _, err = run(["--library", str(self.lib)], embed_fn=lambda t: [1.0])
        self.assertEqual(rc, 2)

    def test_library_not_found_exits_2(self):
        rc, _, err = run(["--text", "x", "--library", "/no/such/lib/zzz"], embed_fn=lambda t: [1.0])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
