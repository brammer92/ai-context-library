"""Tests for scripts.validate_bounded."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import validate_bounded  # noqa: E402


def _write(library: Path, name: str, body: str, *, cap: int, ts: str = "2026-05-11T00:00:00Z") -> Path:
    p = library / name
    p.write_text(
        f'---\nupdated_at: "{ts}"\ncap: {cap}\n---\n{body}\n',
        encoding="utf-8",
    )
    return p


class TestValidateBounded(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_memory_md(self):
        p = _write(self.lib, "MEMORY.md", "hi", cap=2200)
        self.assertEqual(validate_bounded.validate(p), [])

    def test_unknown_file_rejected(self):
        p = self.lib / "RANDOM.md"
        p.write_text('---\nupdated_at: "2026-05-11T00:00:00Z"\ncap: 100\n---\nhi\n', encoding="utf-8")
        errors = validate_bounded.validate(p)
        self.assertTrue(errors)
        self.assertIn("not a registered bounded file", errors[0])

    def test_over_cap(self):
        body = "x" * 1500
        p = _write(self.lib, "USER.md", body, cap=1375)
        errors = validate_bounded.validate(p)
        self.assertTrue(any("exceeds cap" in e for e in errors))

    def test_cap_mismatch(self):
        p = _write(self.lib, "MEMORY.md", "hi", cap=9999)
        errors = validate_bounded.validate(p)
        self.assertTrue(any("does not match registered" in e for e in errors))

    def test_missing_updated_at(self):
        p = self.lib / "CONSTRAINTS.md"
        p.write_text("---\ncap: 4000\n---\nhi\n", encoding="utf-8")
        errors = validate_bounded.validate(p)
        self.assertTrue(any("updated_at: missing" in e for e in errors))

    def test_bad_iso(self):
        p = self.lib / "MEMORY.md"
        p.write_text('---\nupdated_at: "not a date"\ncap: 2200\n---\nhi\n', encoding="utf-8")
        errors = validate_bounded.validate(p)
        self.assertTrue(any("ISO-8601" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
