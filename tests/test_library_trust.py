"""Tests for scripts.library_trust — deterministic trust scoring.

No model, no backend: trust is a transparent weighted formula, so every
score in these tests is exactly predictable.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import common  # noqa: E402
import library_trust as lt  # noqa: E402

NOW = datetime(2026, 5, 14, tzinfo=timezone.utc)


def meta_for(*, importance="medium", updated_days_ago=0) -> dict:
    updated = (NOW - timedelta(days=updated_days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": "mem_x", "title": "X", "type": "decision", "scope": "project",
        "agent_scope": ["*"], "tags": ["t"], "importance": importance,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": updated, "source": "claude-code",
    }


def write_memory(lib: Path, mem_id: str, body: str, *, importance="medium",
                 updated_days_ago=0) -> Path:
    m = meta_for(importance=importance, updated_days_ago=updated_days_ago)
    m["id"] = mem_id
    m["title"] = mem_id
    p = lib / "memories" / "decisions" / f"{mem_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(common.dump_frontmatter(m, f"# {mem_id}\n\n{body}\n"), encoding="utf-8")
    return p


def run(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = lt.main(args)
    return rc, out.getvalue(), err.getvalue()


class TestComputeTrust(unittest.TestCase):
    def test_clamped_to_unit_interval(self):
        hi = lt.compute_trust(meta_for(importance="critical", updated_days_ago=0),
                              ref_count=99, promoted=True, now=NOW)
        lo = lt.compute_trust(meta_for(importance="low", updated_days_ago=99999),
                              ref_count=0, promoted=False, now=NOW)
        self.assertLessEqual(hi, 1.0)
        self.assertGreaterEqual(lo, 0.0)

    def test_importance_ordering(self):
        scores = [
            lt.compute_trust(meta_for(importance=i), ref_count=0, promoted=False, now=NOW)
            for i in ("low", "medium", "high", "critical")
        ]
        self.assertEqual(scores, sorted(scores))
        self.assertTrue(len(set(scores)) == 4)  # strictly increasing

    def test_reference_count_caps_at_three(self):
        a = lt.compute_trust(meta_for(), ref_count=3, promoted=False, now=NOW)
        b = lt.compute_trust(meta_for(), ref_count=50, promoted=False, now=NOW)
        self.assertEqual(a, b)

    def test_promotion_bonus_applied(self):
        without = lt.compute_trust(meta_for(), ref_count=0, promoted=False, now=NOW)
        with_ = lt.compute_trust(meta_for(), ref_count=0, promoted=True, now=NOW)
        self.assertGreater(with_, without)

    def test_age_decay_lowers_score(self):
        fresh = lt.compute_trust(meta_for(updated_days_ago=0), ref_count=0, promoted=False, now=NOW)
        old = lt.compute_trust(meta_for(updated_days_ago=400), ref_count=0, promoted=False, now=NOW)
        self.assertGreater(fresh, old)

    def test_fresh_critical_referenced_promoted_scores_high(self):
        s = lt.compute_trust(meta_for(importance="critical", updated_days_ago=0),
                             ref_count=3, promoted=True, now=NOW)
        self.assertGreaterEqual(s, 0.9)


class TestScoreLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_cross_references(self):
        write_memory(self.lib, "mem_target", "A durable decision about networking.")
        write_memory(self.lib, "mem_citer", "This builds on mem_target and extends it.")
        results = {r["id"]: r for r in lt.score_library(self.lib, now=NOW)}
        self.assertEqual(results["mem_target"]["ref_count"], 1)
        self.assertEqual(results["mem_citer"]["ref_count"], 0)

    def test_detects_promotion_from_memory_md(self):
        write_memory(self.lib, "mem_promoted", "A durable decision worth keeping in focus.")
        write_memory(self.lib, "mem_plain", "A durable decision not in the working set.")
        (self.lib / "MEMORY.md").write_text(
            common.dump_frontmatter(
                {"updated_at": "2026-05-14T00:00:00Z", "cap": 2200},
                "# MEMORY\n\n## Current focus\n\nSee mem_promoted for the networking call.\n",
            ),
            encoding="utf-8",
        )
        results = {r["id"]: r for r in lt.score_library(self.lib, now=NOW)}
        self.assertTrue(results["mem_promoted"]["promoted"])
        self.assertFalse(results["mem_plain"]["promoted"])


class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)
        write_memory(self.lib, "mem_one", "A durable decision about the deployment pipeline.")

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_does_not_write(self):
        before = (self.lib / "memories" / "decisions" / "mem_one.md").read_text()
        rc, out, err = run(["--library", str(self.lib)])
        self.assertEqual(rc, 0, msg=err)
        after = (self.lib / "memories" / "decisions" / "mem_one.md").read_text()
        self.assertEqual(before, after)
        self.assertIn("dry-run", (out + err).lower())

    def test_apply_writes_trust_frontmatter(self):
        rc, out, err = run(["--library", str(self.lib), "--apply"])
        self.assertEqual(rc, 0, msg=err)
        text = (self.lib / "memories" / "decisions" / "mem_one.md").read_text()
        meta, _ = common.parse_frontmatter(text)
        self.assertIn("trust", meta)
        self.assertIn("trust_updated_at", meta)
        val = float(meta["trust"])
        self.assertGreaterEqual(val, 0.0)
        self.assertLessEqual(val, 1.0)

    def test_apply_is_idempotent_in_value(self):
        run(["--library", str(self.lib), "--apply"])
        m1, _ = common.parse_frontmatter((self.lib / "memories" / "decisions" / "mem_one.md").read_text())
        run(["--library", str(self.lib), "--apply"])
        m2, _ = common.parse_frontmatter((self.lib / "memories" / "decisions" / "mem_one.md").read_text())
        self.assertEqual(float(m1["trust"]), float(m2["trust"]))

    def test_apply_preserves_required_fields(self):
        run(["--library", str(self.lib), "--apply"])
        import validate_memory
        errs = validate_memory.validate(self.lib / "memories" / "decisions" / "mem_one.md")
        self.assertEqual(errs, [], msg=str(errs))

    def test_json_output_parseable(self):
        rc, out, err = run(["--library", str(self.lib), "--json"])
        self.assertEqual(rc, 0, msg=err)
        payload = json.loads(out)
        self.assertEqual(payload[0]["id"], "mem_one")
        self.assertIn("new_trust", payload[0])

    def test_library_not_found_exits_2(self):
        rc, _, err = run(["--library", "/no/such/lib/zzz"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
