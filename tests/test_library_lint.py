"""Tests for scripts.library_lint."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import init_library  # noqa: E402
import library_lint  # noqa: E402


NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)


def write_memory(library: Path, mid: str, tags: list[str], updated: str, body: str = "Durable content here for testing purposes only.") -> Path:
    folder = library / "memories" / "user"
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{mid}.md"
    tag_block = "\n".join(f"  - {t}" for t in tags)
    p.write_text(
        "---\n"
        f"id: {mid}\n"
        "title: Some Title\n"
        "type: user_preference\n"
        "scope: global\n"
        "agent_scope:\n  - \"*\"\n"
        "tags:\n" + tag_block + "\n"
        "importance: medium\n"
        f'created_at: "{updated}"\n'
        f'updated_at: "{updated}"\n'
        "source: claude-code\n"
        "---\n\n"
        f"# Some Title\n\n{body}\n",
        encoding="utf-8",
    )
    return p


class TestLibraryLint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)
        # Initialize without polluting test output.
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            init_library.main([str(self.lib)])

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_library_reports_no_hard_issues(self):
        report = library_lint.lint(self.lib, now=NOW)
        self.assertEqual(report["schema_failures"], [])
        self.assertEqual(report["stale"], [])
        self.assertEqual(report["cap_findings"], [])

    def test_stale_memory_detected(self):
        write_memory(self.lib, "mem_20250101_old", ["sample"], "2025-01-01T00:00:00Z")
        report = library_lint.lint(self.lib, now=NOW, stale_days=90)
        self.assertTrue(any("mem_20250101_old" in p for (p, _t) in report["stale"]))

    def test_cap_finding_when_over_95_percent(self):
        cap = 1375  # USER.md
        body = "x" * (int(cap * 0.96))
        (self.lib / "USER.md").write_text(
            '---\nupdated_at: "2026-05-11T00:00:00Z"\ncap: 1375\n---\n' + body + "\n",
            encoding="utf-8",
        )
        report = library_lint.lint(self.lib, now=NOW)
        names = [n for (n, _bl, _cap, _pct) in report["cap_findings"]]
        self.assertIn("USER.md", names)

    def test_orphan_memory_listed(self):
        write_memory(self.lib, "mem_20260511_solo", ["sample"], "2026-05-11T00:00:00Z")
        report = library_lint.lint(self.lib, now=NOW)
        ids = [mid for (_p, mid) in report["orphans"]]
        self.assertIn("mem_20260511_solo", ids)

    def test_top_tags_returned(self):
        write_memory(self.lib, "mem_20260511_a", ["docker", "security"], "2026-05-11T00:00:00Z")
        write_memory(self.lib, "mem_20260511_b", ["docker"], "2026-05-11T00:00:00Z")
        report = library_lint.lint(self.lib, now=NOW)
        tags = dict(report["top_tags"])
        self.assertEqual(tags.get("docker"), 2)

    def test_recent_memory_listed(self):
        write_memory(self.lib, "mem_20260511_fresh", ["sample"], "2026-05-10T00:00:00Z")
        report = library_lint.lint(self.lib, now=NOW, recent_days=7)
        ids = [p for (p, _t) in report["recent_memories"]]
        self.assertTrue(any("mem_20260511_fresh" in p for p in ids))

    def test_orphan_not_falsely_referenced_by_substring(self):
        # mem_20260511_a is a substring of mem_20260511_abc. Only the longer
        # id is actually referenced (from USER.md). The shorter id must still
        # be reported as an orphan — substring matching would hide it.
        write_memory(self.lib, "mem_20260511_a", ["sample"], "2026-05-11T00:00:00Z")
        write_memory(self.lib, "mem_20260511_abc", ["sample"], "2026-05-11T00:00:00Z")
        user_md = self.lib / "USER.md"
        original = user_md.read_text(encoding="utf-8")
        user_md.write_text(
            original.rstrip("\n") + "\n\n## Refs\n\nSee mem_20260511_abc.\n",
            encoding="utf-8",
        )
        report = library_lint.lint(self.lib, now=NOW)
        orphan_ids = {mid for (_p, mid) in report["orphans"]}
        self.assertIn("mem_20260511_a", orphan_ids)
        self.assertNotIn("mem_20260511_abc", orphan_ids)


if __name__ == "__main__":
    unittest.main()
