# ADR-002: Scripted user turns, and models never author items

## Context
Anthropic's guidance asks for honesty about simulation and for internal validity free of
contamination. Claude is a model under test and also the coding assistant on this repo.

## Decision
v0 user turns are scripted, not model-simulated; every scenario runs the same turns regardless
of the model's replies. Scenario spines (situation, turns, answer keys, tier) are authored by the
PI; Claude formats them to YAML and never authors items. `tests/fixtures/scenarios/` is
Claude-written plumbing data carrying `reviewed_by: fixture`, a reserved reviewer that marks
test-only provenance: a fixture may be `promoted` so the tests exercise the promoted path, and every
run that contains one is recorded as draft and never reported (amended 2026-09-09 after the external
review of 5993ca2 found a promoted fixture beside a "draft only" rule). A simulated user is a
hypothetical seam with one adapter and is not built.

## Consequences
Multi-turn realism is limited to escalation the author scripted; the caveat is stated in the EOI.
Every reported item has `reviewed_by` naming the promoting expert.
