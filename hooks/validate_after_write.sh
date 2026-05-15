#!/usr/bin/env bash
# Validate writes that land under the AI context library subtree.
#
# Runs at PostToolUse on Write|Edit. Exits non-zero if the just-written
# file fails memory/skill validation or the secret scan, so Claude
# surfaces the error to the user before /library:review is attempted.
set -euo pipefail

# Read tool input from stdin.
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

# Only run on paths under the allowed library subtree.
case "${REL}" in
  memories/*|skills/*|context/*|prompts/*|templates/*|schemas/*) ;;
  *) exit 0 ;;
esac

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

if [[ ! -f "${FILE_PATH}" ]]; then
  exit 0
fi

# Memory files.
if [[ "${REL}" == memories/*.md || "${REL}" == memories/*/*.md ]]; then
  if ! python3 "${PLUGIN_ROOT}/scripts/validate_memory.py" "${FILE_PATH}" 1>&2; then
    echo "  remediation: fix the validation errors above before committing." 1>&2
    exit 1
  fi
fi

# Skill files.
if [[ "${REL}" == skills/*/SKILL.md ]]; then
  if ! python3 "${PLUGIN_ROOT}/scripts/validate_skill.py" "${FILE_PATH}" 1>&2; then
    echo "  remediation: fix the skill validation errors above before committing." 1>&2
    exit 1
  fi
fi

# Always scan for secrets.
if ! python3 "${PLUGIN_ROOT}/scripts/scan_secrets.py" "${FILE_PATH}" 1>&2; then
  echo "  remediation: remove any secrets and rewrite the file." 1>&2
  exit 1
fi

exit 0
