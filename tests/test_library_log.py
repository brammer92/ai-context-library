"""Tests for scripts.library_log."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import library_log  # noqa: E402


class TestLibraryLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_log_with_header(self):
        when = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
        path = library_log.append(self.lib, "init", "library initialized", when=when)
        text = path.read_text(encoding="utf-8")
        self.assertIn("# log", text)
        self.assertIn("[2026-05-11T12:00:00Z] init | library initialized", text)

    def test_newest_on_top(self):
        first_ts = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
        second_ts = datetime(2026, 5, 11, 11, 0, 0, tzinfo=timezone.utc)
        library_log.append(self.lib, "ingest", "first", when=first_ts)
        library_log.append(self.lib, "ingest", "second", when=second_ts)
        text = (self.lib / "log.md").read_text(encoding="utf-8")
        # Second (newer) should appear before first.
        second_idx = text.index("[2026-05-11T11:00:00Z]")
        first_idx = text.index("[2026-05-11T10:00:00Z]")
        self.assertLess(second_idx, first_idx)

    def test_detail_indented(self):
        when = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
        library_log.append(
            self.lib, "lint", "found issues",
            detail="2 stale memories\n1 over-cap bounded file",
            when=when,
        )
        text = (self.lib / "log.md").read_text(encoding="utf-8")
        self.assertIn("    2 stale memories", text)
        self.assertIn("    1 over-cap bounded file", text)

    def test_appends_to_existing_log(self):
        existing = "# log\n\nIntro paragraph.\n\n## [2026-05-10T00:00:00Z] init | old\n"
        (self.lib / "log.md").write_text(existing, encoding="utf-8")
        library_log.append(
            self.lib, "write", "new file",
            when=datetime(2026, 5, 11, tzinfo=timezone.utc),
        )
        text = (self.lib / "log.md").read_text(encoding="utf-8")
        new_idx = text.index("[2026-05-11T00:00:00Z]")
        old_idx = text.index("[2026-05-10T00:00:00Z]")
        self.assertLess(new_idx, old_idx)
        # The original intro paragraph survives.
        self.assertIn("Intro paragraph.", text)


if __name__ == "__main__":
    unittest.main()
