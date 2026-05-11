#!/usr/bin/env python3
"""Scan a file or directory for likely secrets.

Exit codes:
    0  clean
    1  at least one finding
    2  bad invocation

Findings are printed as `path:line:pattern_name: redacted`. Full secret
values never appear in stdout. Binary files and well-known dependency
directories are skipped.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Files with these extensions are scanned. Plus extensionless text files
# (sniff first 512 bytes for null bytes).
TEXT_EXTENSIONS = {
    ".md", ".yml", ".yaml", ".json", ".toml",
    ".env", ".txt", ".sh", ".py", ".ini", ".cfg", ".conf",
}

# Directories that are skipped entirely.
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", "dist", "build",
    # The plugin's own tests/ contains fake-secret fixtures for the scanner.
    # Context libraries are documentation, not code, so they should not
    # have a top-level tests/ folder either.
    "tests",
}

# (name, compiled regex). Order matters: more specific patterns first.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("github_pat_classic", re.compile(r"\bghp_[A-Za-z0-9]{20,}\b")),
    ("github_pat_fine_grained", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[bp]-[A-Za-z0-9-]{10,}\b")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "aws_secret_access_key",
        re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{30,}"),
    ),
    (
        "vendor_env_token",
        re.compile(
            r"(?i)\b(OPENAI|ANTHROPIC|GITHUB|GITLAB|NPM|AZURE|GOOGLE)_"
            r"(API_)?(TOKEN|KEY|SECRET)\s*[:=]\s*['\"]?\S+",
        ),
    ),
    (
        "generic_credential",
        re.compile(
            r"(?i)\b(password|passwd|secret|token|api[_-]?key|apikey)\s*[:=]\s*"
            r"['\"]?[^\s'\"#]{6,}",
        ),
    ),
    ("pem_private_key", re.compile(r"-----BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----")),
]


def redact(s: str) -> str:
    """Keep the first 3 and last 4 characters; star the middle (min 4 stars)."""
    if len(s) <= 8:
        return "*" * max(4, len(s))
    head, tail = s[:3], s[-4:]
    middle_len = max(4, len(s) - 7)
    return f"{head}{'*' * middle_len}{tail}"


def is_binary(path: Path) -> bool:
    """Sniff the first 512 bytes for null bytes."""
    try:
        with path.open("rb") as f:
            chunk = f.read(512)
    except OSError:
        return True
    return b"\x00" in chunk


def should_scan_file(path: Path) -> bool:
    name = path.name
    if name in {".DS_Store"}:
        return False
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    # Extensionless files: scan if they appear textual.
    if path.suffix == "":
        return not is_binary(path)
    return False


def is_env_filename(path: Path) -> tuple[bool, str | None]:
    """Return (is_env, finding_label).

    `.env`, `.env.local`, `.env.production`, etc. -> finding.
    `.env.example`, `.env.sample` -> not flagged.
    """
    name = path.name
    if not name.startswith(".env"):
        return False, None
    if name in {".env.example", ".env.sample", ".env.template"}:
        return False, None
    # `.env` or `.env.something`.
    if name == ".env" or re.match(r"^\.env\..+$", name):
        return True, "env_file_present"
    return False, None


def scan_file(path: Path) -> list[tuple[Path, int, str, str]]:
    findings: list[tuple[Path, int, str, str]] = []
    is_env, env_label = is_env_filename(path)
    if is_env:
        findings.append((path, 0, env_label or "env_file_present", redact(path.name)))
        # Continue scanning contents too — but for an actual .env file we
        # don't want to read its contents into memory if we can avoid it.
        # We still scan to highlight specific lines if they match.

    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, start=1):
                for name, regex in PATTERNS:
                    for match in regex.finditer(line):
                        findings.append((path, lineno, name, redact(match.group(0))))
    except OSError as exc:
        print(f"warning: could not read {path}: {exc}", file=sys.stderr)
    return findings


def walk_targets(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    files: list[Path] = []
    for entry in root.rglob("*"):
        if not entry.is_file():
            continue
        # Skip any path passing through a skip dir.
        if any(part in SKIP_DIRS for part in entry.parts):
            continue
        if should_scan_file(entry) or is_env_filename(entry)[0]:
            files.append(entry)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan a file or directory for likely secrets.",
    )
    parser.add_argument("target", help="File or directory to scan.")
    args = parser.parse_args(argv)

    root = Path(args.target).expanduser().resolve()
    if not root.exists():
        print(f"error: target does not exist: {root}", file=sys.stderr)
        return 2

    files = walk_targets(root)
    all_findings: list[tuple[Path, int, str, str]] = []
    for f in files:
        all_findings.extend(scan_file(f))

    for path, lineno, name, redacted in all_findings:
        loc = f"{path}:{lineno}" if lineno > 0 else f"{path}"
        print(f"{loc}:{name}: {redacted}")

    distinct_files = {f for (f, _l, _n, _r) in all_findings}
    print(
        f"Secret scan: {len(all_findings)} finding(s) in "
        f"{len(distinct_files)} file(s).",
    )
    return 1 if all_findings else 0


if __name__ == "__main__":
    sys.exit(main())
