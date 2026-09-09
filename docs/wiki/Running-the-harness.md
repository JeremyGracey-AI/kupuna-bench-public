# Running the harness

Everything below runs without API keys except the live-model steps. Python 3.12 and
[uv](https://docs.astral.sh/uv/) are the only prerequisites.

## Install and prove the plumbing

```bash
git clone {{REPO_URL}}.git
cd kupuna-bench-public
uv sync --all-groups
uv run kupuna-bench validate tests/fixtures/scenarios
uv run kupuna-bench run --fake --scenarios tests/fixtures/scenarios --allow-draft
```

`--fake` swaps scripted adapters into both seams (`Chat` and `Judge`), so the whole pipeline runs and
writes a run record with no network. CI runs this plumbing gate on every push, keyless. The gate before
any claim of done is `scripts/gate.sh`: the same four CI steps (lint, types, tests, plumbing run), one
per line, exiting on the first failure. `git config core.hooksPath .githooks` once per clone runs it
as a pre-commit hook.

## Configure live models

Settings come from the environment or a `.env` file, which is never committed. Keys are read only in
`src/kupuna_bench/cli.py`.

| Variable | Meaning | Default |
|---|---|---|
| `OPENROUTER_API_KEY` | Key for every model id containing `/` | unset |
| `ANTHROPIC_API_KEY` | Key for model ids without `/`, sent to the Anthropic API | unset |
| `KUPUNA_MODELS` | Comma-separated models under test | `anthropic/claude-sonnet-4.6,openai/gpt-5,google/gemini-2.5-pro,meta-llama/llama-4-maverick` |
| `KUPUNA_JUDGE` | Judge model id | `mistralai/mistral-large-2512` |
| `KUPUNA_CODERS` | Comma-separated coder model ids for `code` | `mistralai/mistral-large-2512,openai/gpt-5,google/gemini-2.5-pro` |
| `KUPUNA_SPEND_CAP_USD` | Cap on model-under-test spend per run, in USD | `40.0` |
| `KUPUNA_SCENARIOS` | Default scenario directory | `scenarios/v0` |
| `KUPUNA_RESULTS` | Default results directory | `results` |

A model id with a `/` goes through OpenRouter and its vendor prefix is its family; an id without one
goes to the Anthropic API. The judge follows the same grammar. No transcript is graded by a judge from
the same family as the model that produced it: `run` raises `JudgeFamilyConflict` before the first
paid call.

## Commands

| Command | What it does | Options |
|---|---|---|
| `validate [DIR]` | Validates every scenario YAML and prints one PI-facing message per problem, all files at once | `DIR` defaults to `scenarios/v0` |
| `run` | Claims `results/run-YYYY-MM-DD-N/`, writes its manifest there, runs every promoted scenario in both variants against each model, journals each cell, judges every reply against the conversation so far and that turn's key, writes the append-only record `results/run-YYYY-MM-DD-N.md` and its JSON | `--fake`, `--scenarios`, `--allow-draft`, `--runs` (default 3), `--spend-cap`, `--out`, `--models`, `--judge`, `--system-prompt`, `--max-tokens` (default 2048), `--rubric`, `--resume DIR` |
| `regrade RESULT.json` | Re-judges the kept transcripts of a previous run with a different judge: the judge-calibration loop; the new record names its source run | `--judge`, `--scenarios`, `--out`, `--fake`, `--max-tokens`, `--rubric` |
| `code RESULT.json` | Blind multi-family grounded-theory coding of the run's transcripts with a forcing audit; writes a coding JSON and a memo under `docs/memos/` | `--coders`, `--orders` (default 2), `--seed` (default 0), `--human-codes`, `--out`, `--fake` |
| `agreement LABELS.csv... --result RESULT.json` | Human–human and judge–human agreement: quadratic-weighted κ on severity with a bootstrap CI, plain κ on pass/fail, on direction, and on the joint label; S2+ confusions per direction; transcript-level A/B outcomes; the calibration verdict | `--out`, `--key` (decoding map for blinded sheets), `--min-kappa` (default 0.70), `--rubric` |
| `chart RESULT.json` | Renders the Direction A/B failure-rate chart as SVG | `--out` |

## What a run enforces

- Only `status: promoted` scenarios run unless `--allow-draft`; each row records which.
- A failed chat call or malformed judge output becomes a row with an `error`; the run continues and
  the record counts it.
- The record names every model id, the judge, the number of runs, the dataset hash (content fields
  only, so promoting an item between a run and a regrade is not a mismatch), and spend as a per-run
  delta.
- Records are append-only: `run-YYYY-MM-DD-N` increments `N` over records, JSON sidecars, and run
  directories, and the id is claimed by creating the directory before anything is written. The
  JSON, SVG, and run directory (manifest, journal) are git-ignored; the markdown record is committed
  and names its run id, code SHA, and manifest.
- The judge grades one reply at a time and sees only the conversation up to that reply, that turn's
  answer key, and the item's domain and tier; never the variant, persona, situation, or risk cues.
- The age-cue contrast is paired on (scenario, model, run) units: the summary reports pairs complete
  over total, pairs lost by arm, bounds that let each lost arm be a pass or a fail, and a
  scenario-cluster bootstrap interval. Variant order is counterbalanced.
- A reply cut off by the token limit is retried once at double the limit; one still cut off, one the
  provider filtered, and an empty one are error rows by kind, excluded from the rates and counted.
- A scenario with `reviewed_by: fixture` is test data: any run containing one is recorded as draft.

## Labeling and calibration

Human labels are CSVs with the columns in `labels/README.md`. `scripts/make_label_templates.py`
writes one blank template per labeler plus a reading sheet from a results JSON: opaque item ids,
shuffled order, no model, condition, run index, or verdict, and each turn's answer key. The decoding
map is written next to the results JSON; labelers fill `severity` and `direction` blind, then
`agreement --key` compares them with each other and with the judge and prints the calibration
verdict (severity κ and direction κ against each human).
