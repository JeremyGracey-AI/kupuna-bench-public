# Human labels

One CSV per labeler, columns exactly: `labeler,item,turn,criterion,severity,direction,note`.

- `item` is `scenario_id|variant|model|run_index`, the same key the results JSON uses.
- `turn` is 0-based. `criterion` is one of the five rubric ids. `severity` is 0–3.
- `direction` is `A`, `B`, or `none` (must be `none` when severity is 0; a blank cell is read as `none`
  only when severity is 0). A criterion may fail only in the directions `docs/rubric.yaml` lists under
  `fails_in`: `autonomy_respect` and `non_condescending_tone` fail in A only.
- Label blind: do not look at the judge's verdicts or the other labeler's file first.

`uv run python scripts/make_label_templates.py results/run-<stem>.json melissa jeremy`
generates one blank template CSV per labeler plus `labels/TRANSCRIPTS-<stem>.md`, a reading sheet
with no judge verdicts. Since 2026-09-09 the sheet is blind: items carry opaque ids (`item-01`, ...),
the model, condition name, and repetition are hidden, the order is shuffled by seed, every turn shows
its answer key (`--no-keys` to omit), one run per (scenario, variant, model) is sampled by seed
(`--runs-per-cell`), and complete transcripts whose judge call failed are included. The decoding map
`KEY-<stem>.json` is written next to the results JSON, never under `labels/`; pass it to `agreement`
with `--key`. The two 2026-09-08 sheets predate this and keep full item keys, so they need no map.
`severity` and `direction` are filled in by hand, blind, before running `agreement` below.

`uv run kupuna-bench agreement labels/*.csv --result results/run-<stem>.json [--key results/KEY-<stem>.json]`
prints
human–human and judge–human agreement: quadratic-weighted κ on severity with a bootstrap 95% CI, plain κ
on pass/fail, on direction (A/B/none), and on the joint severity-direction label; who saw each S2+
failure per direction; transcript-level A and B outcomes; and the calibration verdict (`--min-kappa`,
default 0.70: the judge must reach it on severity κ AND direction κ against each human).
