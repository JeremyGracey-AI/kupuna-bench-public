# ADR-007: `scenarios/probe/` is engineering calibration, never reported

## Context
The ageism thesis rests on an untested assumption: that a later-life cue alone changes a
model's answer. `PIVOT.md` (2026-09-08) calls for a 72-hour go/no-go on that assumption before
the PI's `scenarios/v0/` spines exist, so the harness needs something runnable now.

## Decision
`scenarios/probe/` holds probe spines authored by a human (Jeremy Gracey, technical lead), formatted to
YAML by Claude; every item is `status: draft` with `reviewed_by` unset. They are engineering
calibration only: never promoted, never reported as results, and never cited in `docs/eoi/`.
`scenarios/v0/` stays reserved for PI-authored, promotable items. Runs on the probe set carry
`draft: true` in their records and are used only for the go/no-go readout: the age-cue delta on
Direction A, the between-model spread, and judge–human agreement.

## Consequences
A reviewer reading the repo sees why two draft items exist outside `scenarios/v0/` instead of
assuming they are stray or forgotten. ADR-002 holds: models never author items — Claude
formatted these spines, it did not write them. The probe run records stay in `results/` marked
draft, so they are distinguishable at a glance from any future promoted run and cannot be
mistaken for a reported result.
