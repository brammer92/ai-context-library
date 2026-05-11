"""Tests for scripts.scan_secrets."""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scan_secrets  # noqa: E402


def run_scan(target: Path) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = scan_secrets.main([str(target)])
    return rc, buf.getvalue()


class TestScanSecrets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, content: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_github_pat_detected_and_redacted(self):
        secret = "ghp_" + "a" * 30 + "abcd"
        self.write("notes.md", f"my token: {secret}\n")
        rc, out = run_scan(self.root)
        self.assertEqual(rc, 1)
        self.assertIn("github_pat_classic", out)
        self.assertNotIn(secret, out, "full secret leaked")

    def test_openai_key_detected(self):
        secret = "sk-" + "X" * 30
        self.write("creds.md", f"OPENAI_API_KEY = {secret}\n")
        rc, out = run_scan(self.root)
        self.assertEqual(rc, 1)
        # Could be matched by openai_key OR vendor_env_token; either is fine.
        self.assertTrue("openai_key" in out or "vendor_env_token" in out)
        self.assertNotIn(secret, out)

    def test_pem_block_detected(self):
        body = (
            "-----BEGIN PRIVATE KEY-----\n"
            "MIIBVAIBA...\n"
            "-----END PRIVATE KEY-----\n"
        )
        self.write("key.txt", body)
        rc, out = run_scan(self.root)
        self.assertEqual(rc, 1)
        self.assertIn("pem_private_key", out)

    def test_env_file_flagged(self):
        self.write(".env", "")
        rc, out = run_scan(self.root)
        self.assertEqual(rc, 1)
        self.assertIn("env_file_present", out)

    def test_env_example_not_flagged(self):
        self.write(".env.example", "FOO=bar\n")
        rc, out = run_scan(self.root)
        self.assertEqual(rc, 0)
        self.assertNotIn("env_file_present", out)

    def test_generic_credential_password(self):
        self.write("config.md", 'password = "hunter2hunter2"\n')
        rc, _ = run_scan(self.root)
        self.assertEqual(rc, 1)

    def test_clean_markdown(self):
        self.write("README.md", "This is a clean README file.\n")
        rc, out = run_scan(self.root)
        self.assertEqual(rc, 0)
        self.assertIn("0 finding(s)", out)

    def test_binary_file_skipped(self):
        path = self.root / "blob.bin"
        path.write_bytes(b"\x00\x01\x02ghp_" + b"a" * 30)
        rc, _ = run_scan(self.root)
        self.assertEqual(rc, 0)

    def test_node_modules_skipped(self):
        self.write("node_modules/pkg/.env", "TOKEN=ghp_" + "a" * 30)
        rc, out = run_scan(self.root)
        self.assertEqual(rc, 0, msg=out)

    def test_redaction_format(self):
        secret = "ghp_" + "b" * 30 + "abcd"
        self.write("notes.md", f"token: {secret}\n")
        _, out = run_scan(self.root)
        self.assertNotIn(secret, out)
        # Redacted should keep first 3 and last 4.
        self.assertIn("ghp", out)
        self.assertIn("abcd", out)


if __name__ == "__main__":
    unittest.main()
