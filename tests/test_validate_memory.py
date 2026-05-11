"""Tests for scripts.validate_memory."""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import validate_memory  # noqa: E402


VALID = """---
id: mem_20260511_docker_security
title: Docker Security Preference
type: security_note
scope: global
agent_scope:
  - "*"
tags:
  - docker
  - security
importance: high
created_at: "2026-05-11T00:00:00Z"
updated_at: "2026-05-11T00:00:00Z"
source: claude-code
---

# Docker Security Preference

The user prefers Docker Compose-first self-hosted deployments with strong
security defaults. Agents should avoid mounting `/var/run/docker.sock`
directly unless explicitly approved.
"""


def run(path: Path) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = validate_memory.main([str(path)])
    return rc, out.getvalue(), err.getvalue()


class TestValidateMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, body: str, name: str = "memory.md") -> Path:
        p = self.root / name
        p.write_text(body, encoding="utf-8")
        return p

    def test_valid(self):
        p = self.write(VALID)
        rc, _, err = run(p)
        self.assertEqual(rc, 0, msg=err)

    def test_missing_id(self):
        bad = VALID.replace("id: mem_20260511_docker_security\n", "")
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("id: missing", err)

    def test_id_wrong_prefix(self):
        bad = VALID.replace(
            "id: mem_20260511_docker_security",
            "id: foo_bar_baz",
        )
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("must start with 'mem_'", err)

    def test_invalid_type(self):
        bad = VALID.replace("type: security_note", "type: bogus_type")
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("type:", err)
        self.assertIn("not in allowed values", err)

    def test_capitalized_tag(self):
        bad = VALID.replace("  - docker\n", "  - Docker\n")
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("kebab-case", err)

    def test_invalid_timestamp(self):
        bad = VALID.replace(
            'created_at: "2026-05-11T00:00:00Z"',
            'created_at: "not a date"',
        )
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("created_at", err)

    def test_empty_body(self):
        bad = VALID.split("---", 2)[0] + "---\n" + VALID.split("---", 2)[1] + "---\n"
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("content", err)

    def test_short_body(self):
        head = VALID.split("---", 2)
        bad = "---" + head[1] + "---\nhello\n"
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("too short", err)

    def test_no_frontmatter(self):
        p = self.write("just a body\n")
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("frontmatter", err)

    def test_invalid_scope(self):
        bad = VALID.replace("scope: global", "scope: bogus")
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("scope:", err)


if __name__ == "__main__":
    unittest.main()
