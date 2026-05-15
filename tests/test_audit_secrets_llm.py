"""Tests for scripts.audit_secrets_llm — advisory LLM secret auditor.

Same shape as test_library_contradict: inject a stub judge_fn so the
tests are deterministic and never hit the real API. The real
_anthropic_judge function is only exercised for its no-key path —
verdict quality is a live-API concern.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import audit_secrets_llm as audit  # noqa: E402


def run(args: list[str], judge_fn=None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = audit.main(args, judge_fn=judge_fn)
    return rc, out.getvalue(), err.getvalue()


class TestAuditCore(unittest.TestCase):
    def test_clean_content_returns_clean(self):
        verdict = audit.audit("Lorem ipsum dolor sit amet.",
                              judge_fn=lambda _t: "clean")
        self.assertEqual(verdict, "clean")

    def test_bare_anthropic_key_flagged_by_stub_judge(self):
        """Documents the intent: a bare Anthropic-shaped key MUST be
        classified as likely_secret. The stub mirrors what a real model
        is expected to do; actual model behaviour is a live-API
        concern."""
        def judge(text: str) -> str:
            return "likely_secret" if "sk-ant-" in text else "clean"

        bad = "Set ANTHROPIC_API_KEY to sk-ant-api03-XYZZYabc123"
        self.assertEqual(audit.audit(bad, judge_fn=judge), "likely_secret")

    def test_garbled_judge_response_becomes_unavailable(self):
        verdict = audit.audit("anything",
                              judge_fn=lambda _t: "yeah probably")
        self.assertEqual(verdict, "UNAVAILABLE")

    def test_judge_raises_becomes_unavailable(self):
        def boom(_t):
            raise audit.AuditUnavailable("network (test)")

        self.assertEqual(audit.audit("x", judge_fn=boom), "UNAVAILABLE")

    def test_no_judge_wired_is_unavailable(self):
        self.assertEqual(audit.audit("x", judge_fn=None), "UNAVAILABLE")


class TestAnthropicJudgeNoKey(unittest.TestCase):
    def test_missing_api_key_path(self):
        """The real _anthropic_judge must raise AuditUnavailable when
        no key is set, BEFORE any network call. This is the only branch
        of the real function we can unit-test."""
        saved = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = ""
        try:
            with self.assertRaises(audit.AuditUnavailable):
                audit._anthropic_judge(
                    "anything", key="", model="claude-haiku-4-5-20251001",
                )
        finally:
            if saved is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = saved


class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_file_clean_verdict_prints_line(self):
        f = self.dir / "ok.txt"
        f.write_text("the cat sat on the mat\n", encoding="utf-8")
        rc, out, err = run(
            ["--file", str(f)], judge_fn=lambda _t: "clean",
        )
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("clean", out)
        self.assertIn("ok.txt", out)

    def test_json_output_parseable(self):
        f = self.dir / "x.txt"
        f.write_text("body", encoding="utf-8")
        rc, out, err = run(
            ["--file", str(f), "--json"], judge_fn=lambda _t: "suspicious",
        )
        self.assertEqual(rc, 0, msg=err)
        payload = json.loads(out)
        self.assertEqual(payload["verdict"], "suspicious")
        self.assertEqual(payload["file"], str(f))

    def test_missing_file_exits_2(self):
        rc, _, err = run(
            ["--file", str(self.dir / "nope.txt")],
            judge_fn=lambda _t: "clean",
        )
        self.assertEqual(rc, 2)
        self.assertIn("not a file", err)

    def test_advisory_never_blocks(self):
        """Exit code reflects ONLY operational success, never the LLM
        verdict. A `likely_secret` verdict still exits 0 — the regex
        scanner remains the sole blocking gate."""
        f = self.dir / "x.txt"
        f.write_text("ghp_aaaabbbbccccddddeeeeffff00001111", encoding="utf-8")
        rc, out, _ = run(
            ["--file", str(f)], judge_fn=lambda _t: "likely_secret",
        )
        self.assertEqual(rc, 0)
        self.assertIn("likely_secret", out)


if __name__ == "__main__":
    unittest.main()
