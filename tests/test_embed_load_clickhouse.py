"""Tests for scripts.embed_load_clickhouse.

ClickHouse is never contacted: every test injects a fake ``insert_fn``
that captures the payload, or one that raises ``ClickHouseUnavailable``
to exercise graceful degradation.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import embed_load_clickhouse as elc  # noqa: E402


SAMPLE_RECORDS = {
    "mem_a": {
        "id": "mem_a", "content_hash": "sha256:aa", "model": "nomic-embed-text",
        "dim": 3, "embedded_at": "2026-05-14T10:32:00Z", "type": "decision",
        "tags": ["x", "y"], "vector": [0.1, 0.2, 0.3],
    },
    "mem_b": {
        "id": "mem_b", "content_hash": "sha256:bb", "model": "nomic-embed-text",
        "dim": 3, "embedded_at": "2026-05-14T11:00:00Z", "type": "fact",
        "tags": ["z"], "vector": [0.4, 0.5, 0.6],
    },
}


def write_jsonl(path: Path, records: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(records[k], sort_keys=True) for k in sorted(records)) + "\n",
        encoding="utf-8",
    )


class Capture:
    """A fake insert_fn that records the payload it was handed."""
    def __init__(self):
        self.payloads: list[str] = []

    def __call__(self, payload: str) -> None:
        self.payloads.append(payload)

    @property
    def rows(self) -> list[dict]:
        out = []
        for p in self.payloads:
            out.extend(json.loads(line) for line in p.splitlines() if line.strip())
        return out


def unavailable_insert(payload: str) -> None:
    raise elc.ClickHouseUnavailable("connection refused (test)")


def run(args: list[str], insert_fn) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = elc.main(args, insert_fn=insert_fn)
    return rc, out.getvalue(), err.getvalue()


class TestRowTransform(unittest.TestCase):
    def test_timestamp_converted_to_clickhouse_datetime(self):
        row = elc.to_clickhouse_row(SAMPLE_RECORDS["mem_a"])
        self.assertEqual(row["embedded_at"], "2026-05-14 10:32:00")

    def test_keeps_vector_tags_and_scalars(self):
        row = elc.to_clickhouse_row(SAMPLE_RECORDS["mem_a"])
        self.assertEqual(row["id"], "mem_a")
        self.assertEqual(row["vector"], [0.1, 0.2, 0.3])
        self.assertEqual(row["tags"], ["x", "y"])
        self.assertEqual(row["type"], "decision")
        self.assertEqual(row["content_hash"], "sha256:aa")

    def test_build_payload_is_jsoneachrow(self):
        payload = elc.build_insert_payload(SAMPLE_RECORDS)
        lines = payload.splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            json.loads(line)  # each line must be valid JSON


class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name)
        self.jsonl = self.lib / "embeddings" / "memories.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_loads_all_records(self):
        write_jsonl(self.jsonl, SAMPLE_RECORDS)
        cap = Capture()
        rc, out, err = run(["--library", str(self.lib)], cap)
        self.assertEqual(rc, 0, msg=err)
        self.assertEqual({r["id"] for r in cap.rows}, {"mem_a", "mem_b"})
        self.assertIn("2", out)

    def test_only_filter_loads_one_record(self):
        write_jsonl(self.jsonl, SAMPLE_RECORDS)
        cap = Capture()
        rc, out, err = run(["--library", str(self.lib), "--only", "mem_b"], cap)
        self.assertEqual(rc, 0, msg=err)
        self.assertEqual([r["id"] for r in cap.rows], ["mem_b"])

    def test_missing_jsonl_exits_zero(self):
        cap = Capture()
        rc, out, err = run(["--library", str(self.lib)], cap)
        self.assertEqual(rc, 0)
        self.assertEqual(cap.rows, [])

    def test_empty_jsonl_does_not_call_insert(self):
        self.jsonl.parent.mkdir(parents=True)
        self.jsonl.write_text("", encoding="utf-8")
        cap = Capture()
        rc, _, _ = run(["--library", str(self.lib)], cap)
        self.assertEqual(rc, 0)
        self.assertEqual(cap.payloads, [])

    def test_clickhouse_unavailable_exits_zero(self):
        write_jsonl(self.jsonl, SAMPLE_RECORDS)
        rc, out, err = run(["--library", str(self.lib)], unavailable_insert)
        self.assertEqual(rc, 0, msg="ClickHouse is a cache — its absence must not fail the run")
        self.assertIn("clickhouse", (out + err).lower())

    def test_library_not_found_exits_2(self):
        cap = Capture()
        rc, _, err = run(["--library", "/no/such/library/zzz"], cap)
        self.assertEqual(rc, 2)
        self.assertIn("error", err.lower())


if __name__ == "__main__":
    unittest.main()
