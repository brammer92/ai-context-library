"""Safe git wrappers used by status / commit / sync / review.

Every wrapper invokes git via `subprocess.run` with a list argument (never
`shell=True`). Destructive commands are intentionally not provided.

Forbidden — do NOT add wrappers for any of these:
    git reset --hard
    git clean -fd
    git push --force
    git filter-branch
    git gc --prune=now
    git rebase
    git checkout -- .
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import common


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def is_git_repo(cwd: Path) -> bool:
    result = _run(cwd, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_status_short(cwd: Path) -> list[tuple[str, str]]:
    """Return [(status_code, path), ...]. Empty if no pending changes."""
    if not is_git_repo(cwd):
        return []
    result = _run(cwd, "status", "--short")
    entries: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        # `XY path` — first two chars are status, then a space, then path.
        if len(line) > 3:
            entries.append((line[:2], line[3:]))
    return entries


def git_branch(cwd: Path) -> str:
    if not is_git_repo(cwd):
        return ""
    result = _run(cwd, "branch", "--show-current")
    return result.stdout.strip()


def git_remote_sanitized(cwd: Path) -> str:
    """Return the origin URL with userinfo stripped.

    Hides https://USER:TOKEN@host -> https://host. SSH URLs (git@host:org/repo)
    are returned as-is.
    """
    if not is_git_repo(cwd):
        return ""
    result = _run(cwd, "remote", "get-url", "origin")
    if result.returncode != 0:
        return ""
    url = result.stdout.strip()
    return re.sub(r"^(https?://)[^@/]+@", r"\1", url)


def git_log_one(cwd: Path) -> str:
    if not is_git_repo(cwd):
        return ""
    result = _run(cwd, "log", "-1", "--oneline")
    return result.stdout.strip()


def git_diff(cwd: Path, paths: list[str] | None = None) -> str:
    if not is_git_repo(cwd):
        return ""
    args = ["diff"]
    if paths:
        args.append("--")
        args.extend(paths)
    return _run(cwd, *args).stdout


def git_diff_name_only(cwd: Path) -> list[str]:
    """Files changed vs HEAD, staged or unstaged, plus untracked."""
    if not is_git_repo(cwd):
        return []
    changed: list[str] = []
    tracked = _run(cwd, "diff", "--name-only", "HEAD").stdout.splitlines()
    changed.extend([p for p in tracked if p])
    untracked = _run(cwd, "ls-files", "--others", "--exclude-standard").stdout.splitlines()
    changed.extend([p for p in untracked if p])
    # de-dupe, preserve order
    seen: set[str] = set()
    unique: list[str] = []
    for p in changed:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def git_pull_ff_only(cwd: Path) -> tuple[int, str, str]:
    if not is_git_repo(cwd):
        return (1, "", "not a git repository")
    result = _run(cwd, "pull", "--ff-only")
    return result.returncode, result.stdout, result.stderr


def git_add(cwd: Path, paths: list[str]) -> tuple[int, str, str]:
    """Stage only paths that are under allowed library subtrees.

    Returns (rc, stdout, stderr). If any path is rejected, returns rc=2 with
    the offending path listed in stderr and stages nothing.
    """
    for p in paths:
        rel = Path(p)
        if not common.is_under_allowed_library_path(rel):
            return 2, "", f"refusing to stage path outside allowed library subtree: {p}"
    if not paths:
        return 0, "", ""
    result = _run(cwd, "add", "--", *paths)
    return result.returncode, result.stdout, result.stderr


def git_commit(cwd: Path, message: str) -> tuple[int, str, str]:
    if len(message.strip()) < 10:
        return 2, "", "commit message must be at least 10 characters"
    result = _run(cwd, "commit", "-m", message)
    return result.returncode, result.stdout, result.stderr


__all__ = [
    "is_git_repo",
    "git_status_short",
    "git_branch",
    "git_remote_sanitized",
    "git_log_one",
    "git_diff",
    "git_diff_name_only",
    "git_pull_ff_only",
    "git_add",
    "git_commit",
]
