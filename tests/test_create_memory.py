"""Tests for scripts.create_memory."""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import create_memory  # noqa: E402
import validate_memory  # noqa: E402


def run(args: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = create_memory.main(args)
    return rc, out.getvalue(), err.getvalue()


class TestCreateMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_security_note_routed_to_security_folder(self):
        rc, out, err = run([
            "--content", "The user prefers strong Docker security defaults always.",
            "--type", "security_note",
            "--library", str(self.lib),
            "--tags", "docker,security",
        ])
        self.assertEqual(rc, 0, msg=err)
        files = list((self.lib / "memories" / "security").glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].name.startswith("mem_"))

    def test_fact_routed_to_facts_folder(self):
        rc, _, err = run([
            "--content", "FortiGate syslog stack v1 lives at 10.1.40.11-13 on VLAN 40.",
            "--type", "fact",
            "--library", str(self.lib),
        ])
        self.assertEqual(rc, 0, msg=err)
        files = list((self.lib / "memories" / "facts").glob("*.md"))
        self.assertEqual(len(files), 1)
        # And nothing landed in memories/user/ (which is reserved for
        # type=user_preference).
        self.assertEqual(list((self.lib / "memories" / "user").glob("*.md")), [])

    def test_refuses_overwrite(self):
        args = [
            "--content", "The user prefers Docker Compose for self-hosted deployments.",
            "--type", "user_preference",
            "--title", "Same Title",
            "--library", str(self.lib),
        ]
        rc1, _, err1 = run(args)
        self.assertEqual(rc1, 0, msg=err1)
        rc2, _, err2 = run(args)
        self.assertEqual(rc2, 1)
        self.assertIn("overwrite", err2)

    def test_secret_in_content_blocks_creation(self):
        secret = "ghp_" + "z" * 30 + "abcd"
        rc, _, err = run([
            "--content", f"My durable preference about config: token is {secret} and that is fine.",
            "--type", "user_preference",
            "--library", str(self.lib),
        ])
        self.assertEqual(rc, 1, msg=err)
        # File should have been removed.
        files = list((self.lib / "memories" / "user").glob("*.md"))
        self.assertEqual(files, [])

    def test_dry_run_writes_nothing(self):
        rc, out, _ = run([
            "--content", "The user prefers Docker Compose-first deployments with strong defaults.",
            "--type", "user_preference",
            "--library", str(self.lib),
            "--dry-run",
        ])
        self.assertEqual(rc, 0)
        self.assertIn("---", out)
        self.assertEqual(list((self.lib / "memories").rglob("*.md")), [])

    def test_generated_file_validates(self):
        rc, _, err = run([
            "--content", "The user prefers conventional commits with imperative subject lines.",
            "--type", "user_preference",
            "--library", str(self.lib),
        ])
        self.assertEqual(rc, 0, msg=err)
        files = list((self.lib / "memories" / "user").glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertEqual(validate_memory.validate(files[0]), [])

    def test_id_pattern(self):
        rc, _, _ = run([
            "--content", "The user prefers GitHub Actions over Jenkins for CI pipelines.",
            "--type", "user_preference",
            "--library", str(self.lib),
        ])
        self.assertEqual(rc, 0)
        files = list((self.lib / "memories" / "user").glob("*.md"))
        self.assertRegex(files[0].name, r"^mem_\d{8}_[a-z0-9_]+\.md$")

    def test_secret_in_title_blocks_creation_before_disk_write(self):
        """An AWS access-key id in the title must abort before any slug
        is derived; no file may hit disk under the library tree."""
        rc, _, err = run([
            "--content", "Durable content about a credential rotation pass.",
            "--title", "Rotate AKIAIOSFODNN7EXAMPLE soon",
            "--type", "security_note",
            "--library", str(self.lib),
        ])
        self.assertEqual(rc, 1, msg=err)
        self.assertEqual(list(self.lib.rglob("*.md")), [])
        self.assertIn("credential-shaped token", err)

    def test_secret_content_never_lands_in_library(self):
        """A secret that the pre-scan misses but the post-scan catches
        must never land anywhere under the library tree — atomic write
        means the tempfile lives in /tmp and os.replace is only reached
        after both gates pass."""
        # `password = ...` matches generic_credential post-scan but the
        # pre-scan suppresses env-var refs. A bare token value clears the
        # pre-scan only if the regex it uses is narrower than scan_secrets'.
        # Either way we want zero files under the library on failure.
        secret_body = (
            "Durable content about credential hygiene with a token "
            "embedded here ghp_" + "a" * 30 + "bbbb that should never "
            "land on disk in the library tree."
        )
        rc, _, _ = run([
            "--content", secret_body,
            "--type", "user_preference",
            "--library", str(self.lib),
        ])
        self.assertEqual(rc, 1)
        # Atomic write: the rglob must come up empty for the WHOLE library.
        self.assertEqual(list(self.lib.rglob("*.md")), [])

    def test_no_partial_file_on_validation_failure(self):
        """If validation fails on the tempfile, os.replace is never
        called and the target path must not exist."""
        original_validate = validate_memory.validate
        try:
            validate_memory.validate = lambda path: [
                "forced validation failure for atomic-write test"
            ]
            rc, _, err = run([
                "--content", "A perfectly fine durable preference body line.",
                "--type", "user_preference",
                "--library", str(self.lib),
            ])
        finally:
            validate_memory.validate = original_validate
        self.assertEqual(rc, 1)
        self.assertIn("forced validation failure", err)
        # No file landed anywhere in the library tree.
        self.assertEqual(list(self.lib.rglob("*.md")), [])


if __name__ == "__main__":
    unittest.main()
