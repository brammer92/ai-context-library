#!/usr/bin/env bash
# Auto-maintain index.md and log.md after a write under the library subtree.
#
# Karpathy LLM Wiki pattern: every write produces a log entry; the index is
# regenerated so any agent can locate the new content.
#
# Informational only — always exits 0.
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

# Only run on paths under the library subtree. Includes the bounded root
# files, the auto-maintained indexes, and sources.
case "${REL}" in
  memories/*|skills/*|context/*|prompts/*|templates/*|schemas/*|sources/*|projects/*) ;;
  MEMORY.md|USER.md|CONSTRAINTS.md|CLAUDE.md|AGENTS.md|CHATGPT.md|README.md) ;;
  *) exit 0 ;;
esac

# Skip self-writes to index.md / log.md to avoid infinite loops.
case "${REL}" in
  index.md|log.md) exit 0 ;;
esac

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

# Append a log entry.
python3 "${PLUGIN_ROOT}/scripts/library_log.py" \
  --operation "write" \
  --subject "${REL}" \
  --library "${LIB}" >/dev/null 2>&1 || true

# Regenerate the index.
python3 "${PLUGIN_ROOT}/scripts/library_index.py" "${LIB}" >/dev/null 2>&1 || true

exit 0
