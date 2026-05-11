"""Tests for scripts.common."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Make scripts/ importable for tests run from repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import common  # noqa: E402


class TestFrontmatter(unittest.TestCase):
    def test_parse_basic_scalars_and_list(self):
        text = (
            "---\n"
            "id: mem_x\n"
            'title: "Docker Security"\n'
            "tags:\n"
            "  - docker\n"
            "  - security\n"
            "---\n"
            "Body line 1\n"
            "Body line 2\n"
        )
        meta, body = common.parse_frontmatter(text)
        self.assertEqual(meta["id"], "mem_x")
        self.assertEqual(meta["title"], "Docker Security")
        self.assertEqual(meta["tags"], ["docker", "security"])
        self.assertEqual(body, "Body line 1\nBody line 2\n")

    def test_parse_no_frontmatter(self):
        meta, body = common.parse_frontmatter("just a body\n")
        self.assertEqual(meta, {})
        self.assertEqual(body, "just a body\n")

    def test_parse_unterminated_raises(self):
        with self.assertRaises(ValueError):
            common.parse_frontmatter("---\nkey: val\nno close\n")

    def test_parse_booleans_and_ints(self):
        text = "---\nactive: true\ncount: 7\n---\n"
        meta, _ = common.parse_frontmatter(text)
        self.assertIs(meta["active"], True)
        self.assertEqual(meta["count"], 7)

    def test_round_trip(self):
        meta = {
            "id": "mem_a",
            "title": "Some Title",
            "tags": ["one", "two"],
            "active": True,
        }
        body = "Hello world.\n"
        dumped = common.dump_frontmatter(meta, body)
        meta2, body2 = common.parse_frontmatter(dumped)
        self.assertEqual(meta2["id"], "mem_a")
        self.assertEqual(meta2["title"], "Some Title")
        self.assertEqual(meta2["tags"], ["one", "two"])
        self.assertIs(meta2["active"], True)
        self.assertEqual(body2.rstrip("\n"), body.rstrip("\n"))


class TestCaseHelpers(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(common.slugify("Docker Security Preference!"), "docker-security-preference")
        self.assertEqual(common.slugify("  Multi   Space  "), "multi-space")
        self.assertEqual(common.slugify(""), "")

    def test_is_snake_case(self):
        self.assertTrue(common.is_snake_case("mem_foo_bar"))
        self.assertTrue(common.is_snake_case("a"))
        self.assertFalse(common.is_snake_case("mem-foo"))
        self.assertFalse(common.is_snake_case("Mem_foo"))
        self.assertFalse(common.is_snake_case(""))

    def test_is_kebab_case(self):
        self.assertTrue(common.is_kebab_case("docker-security"))
        self.assertTrue(common.is_kebab_case("docker"))
        self.assertFalse(common.is_kebab_case("Docker"))
        self.assertFalse(common.is_kebab_case("docker_security"))

    def test_is_iso8601(self):
        self.assertTrue(common.is_iso8601("2026-05-11T00:00:00Z"))
        self.assertTrue(common.is_iso8601("2026-05-11T12:34:56+02:00"))
        self.assertFalse(common.is_iso8601("not a date"))
        self.assertFalse(common.is_iso8601(""))
        self.assertFalse(common.is_iso8601(None))  # type: ignore[arg-type]

    def test_is_semver(self):
        self.assertTrue(common.is_semver("1.0.0"))
        self.assertTrue(common.is_semver("12.34.56"))
        self.assertFalse(common.is_semver("1.0"))
        self.assertFalse(common.is_semver("v1.0.0"))


class TestIDs(unittest.TestCase):
    def test_generate_memory_id(self):
        dt = datetime(2026, 5, 11, tzinfo=timezone.utc)
        mid = common.generate_memory_id("Docker Security", dt)
        self.assertRegex(mid, r"^mem_\d{8}_[a-z0-9_]+$")
        self.assertEqual(mid, "mem_20260511_docker_security")

    def test_generate_memory_id_empty_title(self):
        dt = datetime(2026, 5, 11, tzinfo=timezone.utc)
        mid = common.generate_memory_id("!!!", dt)
        self.assertEqual(mid, "mem_20260511_untitled")

    def test_generate_skill_id(self):
        self.assertEqual(
            common.generate_skill_id("Docker Compose Security Review"),
            "skill_docker_compose_security_review",
        )


class TestUsefulContent(unittest.TestCase):
    def test_too_short(self):
        ok, reason = common.useful_content_heuristic("hello")
        self.assertFalse(ok)
        self.assertIn("too short", reason)

    def test_filler(self):
        ok, _ = common.useful_content_heuristic(
            "Maybe check this later, I am not sure what to do here."
        )
        self.assertFalse(ok)

    def test_durable(self):
        body = (
            "The user prefers Docker Compose-first self-hosted deployments "
            "with strong security defaults."
        )
        ok, reason = common.useful_content_heuristic(body)
        self.assertTrue(ok, f"unexpected rejection: {reason}")

    def test_empty(self):
        self.assertFalse(common.useful_content_heuristic("")[0])
        self.assertFalse(common.useful_content_heuristic("   \n\n  ")[0])


class TestPathSafety(unittest.TestCase):
    def test_allowed_subtree(self):
        self.assertTrue(common.is_under_allowed_library_path(Path("memories/user/foo.md")))
        self.assertTrue(common.is_under_allowed_library_path(Path("skills/x/SKILL.md")))
        self.assertTrue(common.is_under_allowed_library_path(Path("CLAUDE.md")))

    def test_traversal_rejected(self):
        self.assertFalse(common.is_under_allowed_library_path(Path("../etc/passwd")))
        self.assertFalse(common.is_under_allowed_library_path(Path("memories/../etc/passwd")))

    def test_absolute_rejected(self):
        self.assertFalse(common.is_under_allowed_library_path(Path("/etc/passwd")))

    def test_disallowed_top(self):
        self.assertFalse(common.is_under_allowed_library_path(Path(".git/HEAD")))
        self.assertFalse(common.is_under_allowed_library_path(Path("scripts/x.py")))

    def test_hermes_harness_root_files(self):
        for name in ("MEMORY.md", "USER.md", "CONSTRAINTS.md"):
            self.assertTrue(common.is_under_allowed_library_path(Path(name)))

    def test_karpathy_indexes_and_sources(self):
        self.assertTrue(common.is_under_allowed_library_path(Path("index.md")))
        self.assertTrue(common.is_under_allowed_library_path(Path("log.md")))
        self.assertTrue(common.is_under_allowed_library_path(Path("sources/2026-05-11-foo.md")))


class TestHermesCapsAndBody(unittest.TestCase):
    def test_caps_exposed(self):
        self.assertEqual(common.HERMES_CAPS["MEMORY.md"], 2200)
        self.assertEqual(common.HERMES_CAPS["USER.md"], 1375)
        self.assertEqual(common.HERMES_CAPS["CONSTRAINTS.md"], 4000)

    def test_body_char_count_strips_frontmatter(self):
        text = "---\nkey: value\n---\nhello\n"
        self.assertEqual(common.body_char_count(text), len("hello\n"))

    def test_body_char_count_no_frontmatter(self):
        text = "hello world\n"
        self.assertEqual(common.body_char_count(text), len(text))


class TestResolveLibrary(unittest.TestCase):
    def test_explicit(self):
        path = common.resolve_library_path(str(REPO_ROOT))
        self.assertEqual(path, REPO_ROOT.resolve())

    def test_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            common.resolve_library_path("/this/path/should/not/exist/zzz")

    def test_env_var(self):
        old = os.environ.get("AI_CONTEXT_LIBRARY_PATH")
        try:
            os.environ["AI_CONTEXT_LIBRARY_PATH"] = str(REPO_ROOT)
            self.assertEqual(common.resolve_library_path(), REPO_ROOT.resolve())
        finally:
            if old is None:
                os.environ.pop("AI_CONTEXT_LIBRARY_PATH", None)
            else:
                os.environ["AI_CONTEXT_LIBRARY_PATH"] = old


if __name__ == "__main__":
    unittest.main()
