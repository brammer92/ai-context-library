#!/usr/bin/env bash
# Embed a memory into the embeddings/ sidecar after it is written.
#
# Embeddings layer: every memory write refreshes its vector in the
# canonical embeddings/memories.jsonl artifact. Degrades gracefully — if
# the embedder is unreachable the underlying script warns and exits 0,
# so this hook never blocks a memory write.
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

# Only act on memory files. Embeddings cover the memories/ archive only.
case "${REL}" in
  memories/*.md|memories/*/*.md) ;;
  *) exit 0 ;;
esac

# Never recurse on the artifact itself.
case "${REL}" in
  embeddings/*) exit 0 ;;
esac

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

# Refresh the canonical JSONL artifact. Graceful on failure.
python3 "${PLUGIN_ROOT}/scripts/embed_memory.py" "${FILE_PATH}" \
  --library "${LIB}" >/dev/null 2>&1 || true

exit 0
