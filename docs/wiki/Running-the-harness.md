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
| `run` | Runs every promoted scenario in both variants against each model, judges every transcript, writes the append-only record `results/run-YYYY-MM-DD-N.md` and its JSON | `--fake`, `--scenarios`, `--allow-draft`, `--runs` (default 3), `--spend-cap`, `--out`, `--models`, `--judge`, `--system-prompt` |
| `regrade RESULT.json` | Re-judges the kept transcripts of a previous run with a different judge: the judge-calibration loop | `--judge`, `--scenarios`, `--out`, `--fake` |
| `code RESULT.json` | Blind multi-family grounded-theory coding of the run's transcripts with a forcing audit; writes a coding JSON and a memo under `docs/memos/` | `--coders`, `--orders` (default 2), `--seed` (default 0), `--human-codes`, `--out`, `--fake` |
| `agreement LABELS.csv... --result RESULT.json` | Human–human and judge–human agreement: quadratic-weighted κ on severity, plain κ on pass/fail | `--out` |
| `chart RESULT.json` | Renders the Direction A/B failure-rate chart as SVG | `--out` |

## What a run enforces

- Only `status: promoted` scenarios run unless `--allow-draft`; each row records which.
- A failed chat call or malformed judge output becomes a row with an `error`; the run continues and
  the record counts it.
- The record names every model id, the judge, the number of runs, the dataset hash (content fields
  only, so promoting an item between a run and a regrade is not a mismatch), and spend as a per-run
  delta.
- Records are append-only: `run-YYYY-MM-DD-N` increments `N`. The JSON and SVG outputs are
  git-ignored; the markdown record is committed.

## Labeling and calibration

Human labels are CSVs with the columns in `labels/README.md`. `scripts/make_label_templates.py`
writes one blank template per labeler plus a judge-verdict-free reading sheet from a results JSON;
labelers fill `severity` and `direction` blind, then `agreement` compares them with each other and
with the judge.
