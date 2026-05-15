"""Tests for scripts.init_library — embeddings/ scaffolding.

init_library has historically had no dedicated test; this file covers
the embeddings-layer addition (the embeddings/ sidecar directory and its
explanatory README).
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import init_library  # noqa: E402


class TestInitLibraryEmbeddings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _init(self) -> int:
        out = io.StringIO()
        with redirect_stdout(out):
            return init_library.main([str(self.lib)])

    def test_creates_embeddings_dir_with_readme(self):
        rc = self._init()
        self.assertEqual(rc, 0)
        self.assertTrue((self.lib / "embeddings").is_dir())
        readme = self.lib / "embeddings" / "README.md"
        self.assertTrue(readme.is_file())
        self.assertIn("memories.jsonl", readme.read_text())

    def test_is_idempotent(self):
        self.assertEqual(self._init(), 0)
        # A second run must not overwrite or error.
        self.assertEqual(self._init(), 0)
        self.assertTrue((self.lib / "embeddings" / "README.md").is_file())


if __name__ == "__main__":
    unittest.main()
