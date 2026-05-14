---
description: Detect tag clusters across memories and propose skill extraction or consolidation. With --embeddings, also finds paraphrased near-duplicates. Read-only — output is suggestions, not mutations.
argument-hint: [--min-cluster N] [--embeddings] [--threshold C]
allowed-tools: Bash, Read
---

# /library:cluster

## Purpose

Surface repeated patterns in the memory archive. Merged Hermes pillars 3
and 5 (feedback + orchestration): when the same tag appears across many
memories, that's a candidate for skill extraction; when overlapping tags
appear in multiple memories, that's a consolidation candidate.

With `--embeddings`, it additionally runs **embedding-based
near-duplicate detection** — grouping memories whose meaning is similar
even when their tags are not, catching "I wrote this twice in different
words" that pure tag-clustering misses.

## Usage

```
/library:cluster
/library:cluster --min-cluster 3
/library:cluster --embeddings
/library:cluster --embeddings --threshold 0.90
```

## Behavior

**Tag clustering (default):**
1. Load every memory's tag set.
2. Group memories by single tag and by tag-pair.
3. For each cluster of size ≥ `--min-cluster` (default 5), report the
   tag(s) and the member memories.
4. For each cluster, propose either a `/library:add-skill` invocation
   (procedure-like tag) or a consolidation suggestion.

**Embedding near-duplicate clustering (`--embeddings`):**
1. Load `embeddings/memories.jsonl`.
2. Group memories whose pairwise embedding cosine is ≥ `--threshold`
   (default 0.92); transitive chains merge into one group.
3. Report each near-duplicate group for review/consolidation.
4. If no embeddings artifact exists, it falls back to tag clustering.

## Safety Rules

- Read-only. Never mutates memories.
- Proposals are suggestions; the user reviews and chooses what to act on.

## Expected Output

A report of clusters (tag clusters, or — with `--embeddings` —
near-duplicate groups) and proposed next actions. The user can take any
subset (or none).

## Implementation

```
# Default: tag clustering.
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/library_cluster.py" \
    "${AI_CONTEXT_LIBRARY_PATH:-$PWD}" \
    --min-cluster 5

# With --embeddings: embedding near-duplicate clustering (tag-cluster fallback built in).
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/library_cluster_embed.py" \
    "${AI_CONTEXT_LIBRARY_PATH:-$PWD}" \
    --threshold 0.92
```

## Safety Reminder

Never auto-create skills. Never auto-merge memories. Surface proposals;
the user decides.
