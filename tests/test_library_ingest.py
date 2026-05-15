"""Tests for scripts.library_ingest."""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import init_library  # noqa: E402
import library_ingest  # noqa: E402


def _init_quiet(lib: Path) -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        init_library.main([str(lib)])


class TestLibraryIngest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)
        _init_quiet(self.lib)
        self.src = self.lib.parent / "src.md"
        self.src.write_text("# Some Article\n\nBody.\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()
        if self.src.exists():
            self.src.unlink()

    def _run(self, args: list[str]) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = library_ingest.main(args)
        return rc, out.getvalue(), err.getvalue()

    def test_copy_and_log(self):
        rc, out, err = self._run([
            "--source", str(self.src),
            "--title", "Some Article",
            "--library", str(self.lib),
        ])
        self.assertEqual(rc, 0, msg=err)
        sources = list((self.lib / "sources").glob("*.md"))
        self.assertEqual(len(sources), 1)
        # Filename pattern: YYYY-MM-DD-<slug>.md
        self.assertRegex(sources[0].name, r"^\d{4}-\d{2}-\d{2}-some-article\.md$")
        log = (self.lib / "log.md").read_text(encoding="utf-8")
        self.assertIn("ingest | Some Article", log)

    def test_refuses_overwrite(self):
        args = [
            "--source", str(self.src),
            "--title", "Same Title",
            "--library", str(self.lib),
        ]
        rc1, _, err1 = self._run(args)
        self.assertEqual(rc1, 0, msg=err1)
        rc2, _, err2 = self._run(args)
        self.assertEqual(rc2, 1)
        self.assertIn("refusing to overwrite", err2)

    def test_secret_in_source_blocks_ingest(self):
        bad = self.lib.parent / "bad.md"
        bad.write_text("api_key = ghp_" + "z" * 30 + "abcd\n", encoding="utf-8")
        try:
            rc, _, err = self._run([
                "--source", str(bad),
                "--library", str(self.lib),
            ])
            self.assertEqual(rc, 1)
            self.assertIn("secret findings", err)
            self.assertEqual(list((self.lib / "sources").glob("*.md")), [])
        finally:
            bad.unlink()

    def test_dry_run_writes_nothing(self):
        rc, out, _ = self._run([
            "--source", str(self.src),
            "--library", str(self.lib),
            "--dry-run",
        ])
        self.assertEqual(rc, 0)
        self.assertIn("would copy", out)
        self.assertEqual(list((self.lib / "sources").glob("*.md")), [])

    def test_secret_content_never_lands_in_library(self):
        """The copy goes to a tempfile in /tmp, gets scanned there, and
        only os.replace's into <library>/sources/ on a clean scan. On a
        positive finding, nothing must land anywhere under the library
        tree."""
        bad = self.lib.parent / "bad-atomic.md"
        bad.write_text(
            "# Bad source\n\napi_key = ghp_" + "a" * 30 + "bbbb\n",
            encoding="utf-8",
        )
        try:
            rc, _, _ = self._run([
                "--source", str(bad),
                "--library", str(self.lib),
            ])
            self.assertEqual(rc, 1)
            # Atomic write: rglob across the whole library tree, not
            # just sources/. Anything anywhere is a failure.
            stray = [
                p for p in self.lib.rglob("*")
                if p.is_file() and "bad-atomic" in p.name
            ]
            self.assertEqual(stray, [])
            self.assertEqual(list((self.lib / "sources").iterdir()), [])
        finally:
            bad.unlink()


if __name__ == "__main__":
    unittest.main()
