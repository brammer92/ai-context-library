"""Tests for scripts.library_promote."""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import init_library  # noqa: E402
import library_promote  # noqa: E402


def _init_quiet(lib: Path) -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        init_library.main([str(lib)])


def write_mem(library: Path, mid: str, body: str = "Durable content statement.") -> Path:
    folder = library / "memories" / "user"
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{mid}.md"
    p.write_text(
        "---\n"
        f"id: {mid}\n"
        "title: Title For Tests\n"
        "type: user_preference\n"
        "scope: global\n"
        "agent_scope:\n  - \"*\"\n"
        "tags:\n  - sample\n"
        "importance: medium\n"
        'created_at: "2026-05-11T00:00:00Z"\n'
        'updated_at: "2026-05-11T00:00:00Z"\n'
        "source: claude-code\n"
        "---\n\n"
        f"# Title For Tests\n\n{body}\n",
        encoding="utf-8",
    )
    return p


class TestLibraryPromote(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)
        _init_quiet(self.lib)

    def tearDown(self):
        self.tmp.cleanup()

    def test_promote_appends_section(self):
        write_mem(self.lib, "mem_20260511_x", "First non-heading line.")
        rc, msg = library_promote.promote(
            self.lib, "mem_20260511_x",
            when=datetime(2026, 5, 11, tzinfo=timezone.utc),
        )
        self.assertEqual(rc, 0, msg=msg)
        text = (self.lib / "MEMORY.md").read_text(encoding="utf-8")
        self.assertIn("Title For Tests", text)
        self.assertIn("`mem_20260511_x`", text)
        self.assertIn("memories/user/mem_20260511_x.md", text)

    def test_missing_memory(self):
        rc, msg = library_promote.promote(self.lib, "mem_does_not_exist")
        self.assertEqual(rc, 1)
        self.assertIn("not found", msg)

    def test_cap_exceeded(self):
        # Bloat MEMORY.md close to cap so a promotion would overflow.
        big = (self.lib / "MEMORY.md")
        body = "x" * 2150
        big.write_text(
            '---\nupdated_at: "2026-05-11T00:00:00Z"\ncap: 2200\n---\n' + body + "\n",
            encoding="utf-8",
        )
        write_mem(self.lib, "mem_20260511_y", "A reasonably long body that pushes us over.")
        rc, msg = library_promote.promote(self.lib, "mem_20260511_y")
        self.assertEqual(rc, 1)
        self.assertIn("cap", msg)

    def test_dry_run(self):
        write_mem(self.lib, "mem_20260511_z", "Body line.")
        rc, msg = library_promote.promote(self.lib, "mem_20260511_z", dry_run=True)
        self.assertEqual(rc, 0)
        self.assertIn("would write MEMORY.md", msg)
        # The actual file should not have been changed.
        text = (self.lib / "MEMORY.md").read_text(encoding="utf-8")
        self.assertNotIn("Title For Tests", text)

    def test_promote_into_adjacent_section_headers(self):
        # MEMORY.md body has `## Current focus` immediately followed by `## Other`,
        # with no blank line or body content between them. The entry must land
        # between the two headings, not after `## Other`.
        (self.lib / "MEMORY.md").write_text(
            '---\nupdated_at: "2026-05-11T00:00:00Z"\ncap: 2200\n---\n'
            "# MEMORY\n\n"
            "## Current focus\n"
            "## Other\nsome other body\n",
            encoding="utf-8",
        )
        write_mem(self.lib, "mem_20260511_adj", "Adjacent section body.")
        rc, msg = library_promote.promote(self.lib, "mem_20260511_adj")
        self.assertEqual(rc, 0, msg=msg)
        text = (self.lib / "MEMORY.md").read_text(encoding="utf-8")
        focus_idx = text.index("## Current focus")
        entry_idx = text.index("mem_20260511_adj")
        other_idx = text.index("## Other")
        self.assertLess(focus_idx, entry_idx)
        self.assertLess(entry_idx, other_idx)

    def test_promote_section_name_substring_collision(self):
        # MEMORY.md has `## Current focus areas` but not `## Current focus`.
        # Promoting with section="Current focus" must NOT inject into the
        # longer-named section; it must create a new `## Current focus`
        # section at the end and leave the existing content untouched.
        (self.lib / "MEMORY.md").write_text(
            '---\nupdated_at: "2026-05-11T00:00:00Z"\ncap: 2200\n---\n'
            "# MEMORY\n\n"
            "## Current focus areas\n\nexisting content under longer header\n",
            encoding="utf-8",
        )
        write_mem(self.lib, "mem_20260511_sub", "Substring collision body.")
        rc, msg = library_promote.promote(
            self.lib, "mem_20260511_sub", section="Current focus"
        )
        self.assertEqual(rc, 0, msg=msg)
        text = (self.lib / "MEMORY.md").read_text(encoding="utf-8")
        # Existing section preserved as-is.
        self.assertIn("## Current focus areas\n\nexisting content under longer header", text)
        # A new section header was appended (one occurrence as a line by itself
        # — distinct from the `## Current focus areas` heading).
        lines = text.splitlines()
        self.assertIn("## Current focus", lines)
        # The new entry must appear AFTER `## Current focus areas`, i.e. in the
        # newly created section, not injected into the longer-named one.
        areas_idx = text.index("## Current focus areas")
        entry_idx = text.index("mem_20260511_sub")
        self.assertLess(areas_idx, entry_idx)
        # And the entry must come AFTER the new bare `## Current focus` line.
        new_header_match = text.rindex("## Current focus\n")
        self.assertLess(new_header_match, entry_idx)

    def test_promote_rollback_on_validation_failure(self):
        write_mem(self.lib, "mem_20260511_rb", "Rollback body.")
        memory_md = self.lib / "MEMORY.md"
        original = memory_md.read_text(encoding="utf-8")

        # Force post-write validation to fail; we want the rollback path.
        original_validate = library_promote.validate_bounded.validate
        library_promote.validate_bounded.validate = lambda _p: ["synthetic error"]
        try:
            rc, msg = library_promote.promote(self.lib, "mem_20260511_rb")
        finally:
            library_promote.validate_bounded.validate = original_validate

        self.assertEqual(rc, 1)
        self.assertIn("rolled back", msg)
        # On-disk content must be exactly what was there before promote ran.
        self.assertEqual(memory_md.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
