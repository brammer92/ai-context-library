"""Tests for scripts.validate_skill."""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import validate_skill  # noqa: E402


VALID = """---
id: skill_docker_compose_security_review
name: Docker Compose Security Review
version: 1.0.0
description: Reviews Docker Compose files for security, reliability, and maintainability.
status: active
tags:
  - docker
  - security
  - devops
agent_scope:
  - "*"
risk_level: medium
created_at: "2026-05-11T00:00:00Z"
updated_at: "2026-05-11T00:00:00Z"
---

# Docker Compose Security Review

## Purpose

Review Docker Compose files for security, reliability, and maintainability issues.

## When To Use

Use this skill when reviewing, creating, or modifying Docker Compose deployments.

## Inputs Expected

- `docker-compose.yml` or `compose.yml`
- `.env.example` when available

## Procedure

1. Check for privileged containers.
2. Check for unsafe Docker socket mounts.

## Output Format

Return a structured review.

## Safety Checks

- Do not recommend mounting `/var/run/docker.sock` directly.

## Failure Modes

- Missing Compose file.
"""


def run(path: Path) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = validate_skill.main([str(path)])
    return rc, out.getvalue(), err.getvalue()


class TestValidateSkill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, body: str, name: str = "SKILL.md") -> Path:
        p = self.root / name
        p.write_text(body, encoding="utf-8")
        return p

    def test_valid(self):
        p = self.write(VALID)
        rc, _, err = run(p)
        self.assertEqual(rc, 0, msg=err)

    def test_invalid_semver(self):
        bad = VALID.replace("version: 1.0.0", "version: 1.0")
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("version:", err)

    def test_invalid_status(self):
        bad = VALID.replace("status: active", "status: bogus")
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("status:", err)

    def test_invalid_risk(self):
        bad = VALID.replace("risk_level: medium", "risk_level: extreme")
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("risk_level:", err)

    def test_missing_required_section(self):
        bad = VALID.replace("## Safety Checks\n\n- Do not recommend mounting `/var/run/docker.sock` directly.\n\n", "")
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("Safety Checks", err)

    def test_missing_id(self):
        bad = VALID.replace("id: skill_docker_compose_security_review\n", "")
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("id: missing", err)

    def test_id_wrong_prefix(self):
        bad = VALID.replace(
            "id: skill_docker_compose_security_review",
            "id: foo_bar",
        )
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("skill_", err)

    def test_capitalized_tag(self):
        bad = VALID.replace("  - docker\n", "  - Docker\n")
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)
        self.assertIn("kebab-case", err)

    def test_empty_body(self):
        head = VALID.split("---", 2)
        bad = "---" + head[1] + "---\n"
        p = self.write(bad)
        rc, _, err = run(p)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
