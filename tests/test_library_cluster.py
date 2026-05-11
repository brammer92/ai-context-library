"""Tests for scripts.library_cluster."""
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
import library_cluster  # noqa: E402


def _init_quiet(lib: Path) -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        init_library.main([str(lib)])


def write_mem(library: Path, idx: int, tags: list[str]) -> None:
    mid = f"mem_20260511_t{idx}"
    folder = library / "memories" / "user"
    folder.mkdir(parents=True, exist_ok=True)
    tag_block = "\n".join(f"  - {t}" for t in tags)
    (folder / f"{mid}.md").write_text(
        "---\n"
        f"id: {mid}\n"
        f"title: Memory {idx}\n"
        "type: user_preference\n"
        "scope: global\n"
        "agent_scope:\n  - \"*\"\n"
        "tags:\n" + tag_block + "\n"
        "importance: medium\n"
        'created_at: "2026-05-11T00:00:00Z"\n'
        'updated_at: "2026-05-11T00:00:00Z"\n'
        "source: claude-code\n"
        "---\n\n"
        f"# Memory {idx}\n\nBody content for memory {idx}.\n",
        encoding="utf-8",
    )


class TestLibraryCluster(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)
        _init_quiet(self.lib)

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_tag_cluster(self):
        for i in range(5):
            write_mem(self.lib, i, ["docker"])
        report = library_cluster.cluster(self.lib, min_cluster=5)
        tags = [t for (t, _c, _m) in report["single_clusters"]]
        self.assertIn("docker", tags)

    def test_pair_tag_cluster(self):
        for i in range(5):
            write_mem(self.lib, i, ["docker", "security"])
        report = library_cluster.cluster(self.lib, min_cluster=5)
        pairs = [p for (p, _c, _m) in report["pair_clusters"]]
        self.assertIn(("docker", "security"), pairs)

    def test_skill_proposal_for_procedure_tag(self):
        for i in range(5):
            write_mem(self.lib, i, ["review"])
        report = library_cluster.cluster(self.lib, min_cluster=5)
        self.assertTrue(any("skill:" in p for p in report["proposals"]))

    def test_below_threshold(self):
        write_mem(self.lib, 0, ["docker"])
        report = library_cluster.cluster(self.lib, min_cluster=5)
        self.assertEqual(report["single_clusters"], [])


if __name__ == "__main__":
    unittest.main()
