# CLAUDE.md — kupuna-bench

This is the public mirror of a private working repository (ADR-008). Read `docs/decisions/` and
`docs/method.md` before major work.

## Stack (non-negotiable)
- Python 3.12, `uv` only (`uv add`, `uv run`), ruff, pyright strict on `src/`, pytest.
- Package `src/kupuna_bench/`. CLI `kupuna-bench` (typer). Config via pydantic-settings in
  `settings.py`; keys are read only in `cli.py`.
- Two seams: `Chat` (`chat.py`) and `Judge` (`judge.py`). Every other module is pure functions
  over frozen pydantic values. Do not add a seam until two adapters exist.

## Rules the code enforces
1. A judge never grades a transcript from its own model family (`JudgeFamilyConflict`).
2. Only `status: promoted` scenarios run unless `--allow-draft`. `Row.status` records which.
3. Failed chat calls and malformed judge output become rows with `error`; the run continues.
4. `run()` and `regrade()` never touch the clock, files, or adapters' construction.
5. `rubric.yaml` changelog entries must cite an existing memo in `docs/memos/` (test-enforced).
6. Scenario content hashes exclude `status` and `reviewed_by`.

## Rules people enforce
- Scenario spines in `scenarios/v0/` are authored by the PI. Claude formats to YAML and never
  authors items (ADR-002). `tests/fixtures/scenarios/` is Claude-written plumbing data, draft only.
- Commits: `[worker]` for agent-produced, `[evaluator]` for handoff/state updates written after a
  verdict, `[human]` for Jeremy's. No AI co-author trailers.
- Never enter anything into the grant application form.
- Before claiming done: `uv run ruff check . && uv run pyright && uv run pytest -q`.
