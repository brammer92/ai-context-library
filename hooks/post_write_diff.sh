#!/usr/bin/env bash
# Print a short diff summary after a write under the AI context library
# subtree. Informational only — always exits 0.
set -euo pipefail

INPUT="$(cat || true)"
if [[ -z "${INPUT}" ]]; then
  exit 0
fi

FILE_PATH="$(printf '%s' "${INPUT}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" 2>/dev/null || true)"
if [[ -z "${FILE_PATH}" ]]; then
  exit 0
fi

LIB="${AI_CONTEXT_LIBRARY_PATH:-${PWD}}"
case "${FILE_PATH}" in
  "${LIB}"/*) REL="${FILE_PATH#${LIB}/}" ;;
  /*) exit 0 ;;
  *) REL="${FILE_PATH}" ;;
esac

case "${REL}" in
  memories/*|skills/*|context/*|prompts/*|templates/*|schemas/*|embeddings/*|README.md|CLAUDE.md|AGENTS.md|CHATGPT.md) ;;
  *) exit 0 ;;
esac

if ! command -v git >/dev/null 2>&1; then
  exit 0
fi

cd "${LIB}" 2>/dev/null || exit 0
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  exit 0
fi

echo "----- AI Context Library: write summary -----"
git status --short || true
git diff --stat -- "${REL}" 2>/dev/null || true
echo "Run /library:review before /library:commit."
echo "---------------------------------------------"
exit 0
