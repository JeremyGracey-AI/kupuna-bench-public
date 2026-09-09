# ADR-008: Public mirror with a fresh history

## Context
ADR-001 planned to go public by transferring the repository to the Foundation's GitHub
organization. That organization does not exist yet, and the working repository holds material
that must not be public before the application is submitted: the draft expression of interest,
the pivot brief and handoff, the build plan, the probe pilot's run records and label sheets, and
personal disclosures meant for the form.

## Decision
The working repository stays private. This public mirror is published under
`JeremyGracey-AI/kupuna-bench-public` with a fresh git history, built by exporting an explicit
allowlist from the working repository at a named commit: the package, tests, CI, packaging,
licenses, `README.md`, `CLAUDE.md`, `AI-USE.md`, the construct, method, and rubric documents,
the decision records, the human-written memo, the sampling log, the brief, the label-template
script and its README, the golden file, and the probe spines (draft calibration items explained
by ADR-007). Excluded by design: `docs/eoi/`, `docs/superpowers/`, `PIVOT.md`, `HANDOFF.md`,
run records, label sheets, and machine-generated coding memos. The mirror is refreshed by
re-running the export; the working repository is the source of truth, and pull requests to
the mirror are replayed into it. When the Foundation's organization exists, the mirror moves
there, closing ADR-001.

## Consequences
Reviewers can read the harness and the method without seeing the application. Nothing from the
working repository's history reaches the mirror; its history starts at the export commit, which
names the working-repository commit it came from.

## Amendment, 2026-09-08
The allowlist grows by `.githooks/`, the tracked pre-commit hook that runs `scripts/gate.sh` (the CI
workflow's steps, one per line, exiting on the first failure), so a clone of either repository installs
the same gate with `git config core.hooksPath .githooks`.
