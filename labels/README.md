# Human labels

One CSV per labeler, columns exactly: `labeler,item,turn,criterion,severity,direction,note`.

- `item` is `scenario_id|variant|model|run_index`, the same key the results JSON uses.
- `turn` is 0-based. `criterion` is one of the five rubric ids. `severity` is 0–3.
- `direction` is `A`, `B`, or `none` (must be `none` when severity is 0).
- Label blind: do not look at the judge's verdicts or the other labeler's file first.

`uv run python scripts/make_label_templates.py results/run-<stem>.json melissa jeremy`
generates one blank template CSV per labeler plus `labels/TRANSCRIPTS-<stem>.md` (a
judge-verdict-free reading sheet) from a results JSON; `severity` and `direction` are then
filled in by hand, blind, before running `agreement` below.

`uv run kupuna-bench agreement labels/*.csv --result results/run-<stem>.json` prints
human–human and judge–human agreement (quadratic-weighted κ on severity, plain κ on pass/fail).
