"""Tests for scripts.create_skill."""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import create_skill  # noqa: E402
import validate_skill  # noqa: E402


def run(args: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = create_skill.main(args)
    return rc, out.getvalue(), err.getvalue()


class TestCreateSkill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_three_files(self):
        rc, _, err = run([
            "--name", "Docker Compose Security Review",
            "--description", "Reviews Docker Compose files for security issues.",
            "--tags", "docker,security,devops",
            "--library", str(self.lib),
        ])
        self.assertEqual(rc, 0, msg=err)
        folder = self.lib / "skills" / "docker-compose-security-review"
        self.assertTrue(folder.is_dir())
        self.assertTrue((folder / "SKILL.md").is_file())
        self.assertTrue((folder / "examples.md").is_file())
        self.assertTrue((folder / "validation.md").is_file())

    def test_generated_skill_validates(self):
        rc, _, err = run([
            "--name", "Sample Skill",
            "--description", "A sample skill for testing.",
            "--tags", "sample,testing",
            "--library", str(self.lib),
        ])
        self.assertEqual(rc, 0, msg=err)
        skill = self.lib / "skills" / "sample-skill" / "SKILL.md"
        self.assertEqual(validate_skill.validate(skill), [])

    def test_refuses_overwrite(self):
        args = [
            "--name", "Same Name",
            "--description", "First creation.",
            "--library", str(self.lib),
        ]
        rc1, _, _ = run(args)
        self.assertEqual(rc1, 0)
        rc2, _, err2 = run(args)
        self.assertEqual(rc2, 1)
        self.assertIn("refusing to overwrite", err2)

    def test_dry_run_writes_nothing(self):
        rc, out, _ = run([
            "--name", "Dry Run Skill",
            "--description", "Just a dry run.",
            "--library", str(self.lib),
            "--dry-run",
        ])
        self.assertEqual(rc, 0)
        self.assertIn("SKILL.md", out)
        self.assertFalse((self.lib / "skills").exists())

    def test_invalid_version(self):
        rc, _, err = run([
            "--name", "Bad Ver",
            "--description", "Has bad version.",
            "--version", "1.0",
            "--library", str(self.lib),
        ])
        self.assertEqual(rc, 2)
        self.assertIn("semver", err)

    def test_id_pattern(self):
        rc, _, _ = run([
            "--name", "Pattern Test Skill",
            "--description", "Confirms generated id pattern.",
            "--library", str(self.lib),
        ])
        self.assertEqual(rc, 0)
        skill = self.lib / "skills" / "pattern-test-skill" / "SKILL.md"
        text = skill.read_text()
        self.assertIn("id: skill_pattern_test_skill", text)


if __name__ == "__main__":
    unittest.main()
