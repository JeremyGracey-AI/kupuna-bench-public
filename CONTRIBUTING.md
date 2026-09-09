# Contributing

## Where the work happens

The public repository, JeremyGracey-AI/kupuna-bench-public, is a mirror with a fresh history,
exported from a private working repository by an explicit allowlist
(`docs/decisions/ADR-008-public-mirror.md`). The working repository is the source of truth. Pull
requests to the mirror are welcome; accepted ones are replayed into the working repository and reach
the mirror at its next export.

## What you can and cannot change

- **Code and tests:** open. Keep the two seams (`Chat`, `Judge`) and the rule that every other
  module is a pure function over frozen values. Run the gate before opening a PR: `scripts/gate.sh`
  is the CI workflow's four steps (lint, types, tests, keyless plumbing run), one per line, and exits
  on the first failure. `git config core.hooksPath .githooks` once per clone runs it on every commit.
- **The rubric:** `docs/rubric.yaml` changes only with a version bump and a changelog entry that
  cites a human-written memo under `docs/memos/`; a test enforces it. The package ships a
  byte-identical copy at `src/kupuna_bench/rubric.yaml` so an installed wheel works; a test fails
  until both match, so copy the policy file over after every change. `--rubric PATH` selects
  another file for one run.
- **Scenarios:** items in the scenario bank are authored by the PI and promoted by name
  (`status: promoted`, `reviewed_by`). Do not submit scenario items; submit an issue describing the
  situation and the PI decides. `scenarios/probe/` is a human-authored calibration set and is not a
  contribution target.
- **Answer keys:** criteria only, never harmful specifics.
- **The wiki:** generated from `docs/` and `docs/wiki/` by `scripts/build_wiki.py`
  (`docs/decisions/ADR-009-generated-wiki.md`). Edit those files, never the wiki pages; the next
  export overwrites them.

## Commits

Prefix records authority: `[worker]` for agent-produced commits, `[evaluator]` for handoff and
state updates, `[human]` for a person's own commits. No AI co-author trailers.

## Model access

Real runs need `OPENROUTER_API_KEY` (and optionally `ANTHROPIC_API_KEY`). Never commit keys;
`.env` is ignored. The scripted adapters (`--fake`) run everything without a key.
