---
name: checking-for-contradictions
description: >
  Internal helper. Invoked by proposing-a-memory to check whether a
  drafted memory conflicts with existing memories. Surfaces
  contradiction candidates by embedding similarity and (optionally) an
  LLM verdict. Not user-facing — no standalone trigger. Read-only;
  never writes.
---

# Checking for Contradictions

## Purpose
Catch the case where a drafted memory conflicts with something already
in the library ("you told me X, now you're saying not-X") *before* the
proposal reaches the user — so the user can resolve the conflict instead
of silently accumulating two contradictory memories.

## When To Use
Only as an internal helper, invoked by `proposing-a-memory` once a
candidate memory has been drafted. No conversational trigger of its own.

## Inputs Expected
- The drafted memory body (or an existing memory id).
- `scripts/library_contradict.py` — does the embedding-NN narrowing and,
  with `--judge` + `ANTHROPIC_API_KEY`, the LLM verdict.
- Read access to `memories/**` for the candidate bodies.

## Procedure
1. Run
   `python3 scripts/library_contradict.py --text "<draft body>" --library <lib> --json`
   (add `--judge` only if an Anthropic key is configured and an LLM
   verdict is wanted).
2. Read the candidates. Each has a `band` ("likely" / "possible"), a
   cosine score, and a `verdict`.
3. If every `verdict` is `UNAVAILABLE` (no judge wired), do not claim
   "no contradictions" — instead surface the `likely`-band candidates as
   "possible conflicts, verdict UNAVAILABLE — eyeball these".
4. If a `verdict` is `contradicts` or `supersedes`, include a
   contradiction block in the proposal with the three resolution
   options (amend the old / supersede the old / co-flag both).
5. Hand the result back to `proposing-a-memory`. Never write anything.

## Output Format
A short block, folded into the PROPOSAL by `proposing-a-memory`:
```
contradicts: <none | mem_x (verdict, cos) ... | UNAVAILABLE — N likely candidate(s)>
  resolve by: [1] amend old  [2] supersede old  [3] co-flag both
```

## Safety Checks
- Read-only. Never call Write, Edit, or any `/library:*` write command.
- Never assert "no contradictions" when the check could not run — say
  "UNAVAILABLE" and list the high-similarity candidates instead.
- The LLM judge is advisory: a `contradicts` verdict opens a resolution
  choice for the user; it never auto-resolves anything.

## Failure Modes
- Voyage AI unreachable or `VOYAGE_API_KEY` unset ->
  `library_contradict.py` exits 0 with a note; report the contradiction
  field as UNAVAILABLE.
- The candidate-narrowing step runs brute-force cosine over the local
  JSONL — no external query service to fall back from; if the JSONL is
  present and the embedder works, candidates are produced.
- No Anthropic key / judge fails -> verdicts are UNAVAILABLE; fall back
  to surfacing `likely`-band candidates for manual review.
- No embeddings generated yet -> no candidates; mark UNAVAILABLE and
  recommend `embed_memory.py --backfill`.
