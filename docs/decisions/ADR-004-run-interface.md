# ADR-004: One `run` call, one `regrade` call, frozen values, no files

## Context
Three interface designs were compared (minimal, flexible, common-caller). The flexible design's
"prior rows" mechanism gives resume, re-judge, panel, and add-model from one rule but costs two
row kinds, run ids, and an eligibility matrix, too much for a two-day build.

## Decision
`run(scenarios, *, models, judge, runs=3, allow_draft=False, spend_cap_usd=None, ...)` returns a
frozen `RunResult` and writes nothing; `regrade(result, scenarios, judge)` re-judges kept
transcripts. Rows are keyed `(scenario, variant, model, run)` internally and streamed via
`on_row` for crash recovery. Scenario hashes cover content only, never `status`/`reviewed_by`.
Resume from prior rows, judge panels, and simulated users are deferred as hypothetical seams.

## Consequences
CI, the pilot, and the full study cross one seam. A crash keeps only what `on_row` streamed;
a rerun repeats the run.
