"""Tests for scripts.library_index."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import init_library  # noqa: E402
import library_index  # noqa: E402


FIXED_NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)


class TestLibraryIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_library_has_all_sections(self):
        init_library.main([str(self.lib)])
        text = library_index.build_index(self.lib, now=FIXED_NOW)
        for section in ("Working Set", "Memories", "Skills", "Context", "Sources", "Projects", "Prompts"):
            self.assertIn(f"## {section}", text)

    def test_memory_appears_in_index(self):
        init_library.main([str(self.lib)])
        # Write a memory file.
        mem = self.lib / "memories" / "user" / "mem_20260511_x.md"
        mem.write_text(
            "---\n"
            "id: mem_20260511_x\n"
            "title: Sample\n"
            "type: user_preference\n"
            "scope: global\n"
            "agent_scope:\n  - \"*\"\n"
            "tags:\n  - sample\n"
            "importance: medium\n"
            'created_at: "2026-05-11T00:00:00Z"\n'
            'updated_at: "2026-05-11T00:00:00Z"\n'
            "source: claude-code\n"
            "---\n\n"
            "# Sample\n\nThis is a sample memory body.\n",
            encoding="utf-8",
        )
        text = library_index.build_index(self.lib, now=FIXED_NOW)
        self.assertIn("Sample", text)
        self.assertIn("memories/user/mem_20260511_x.md", text)

    def test_idempotent(self):
        init_library.main([str(self.lib)])
        a = library_index.build_index(self.lib, now=FIXED_NOW)
        b = library_index.build_index(self.lib, now=FIXED_NOW)
        self.assertEqual(a, b)

    def test_working_set_shows_caps(self):
        init_library.main([str(self.lib)])
        text = library_index.build_index(self.lib, now=FIXED_NOW)
        self.assertIn("MEMORY.md", text)
        self.assertIn("/2200 chars", text)
        self.assertIn("/1375 chars", text)
        self.assertIn("/4000 chars", text)


if __name__ == "__main__":
    unittest.main()
