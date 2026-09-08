# ADR-002: Scripted user turns, and models never author items

## Context
Anthropic's guidance asks for honesty about simulation and for internal validity free of
contamination. Claude is a model under test and also the coding assistant on this repo.

## Decision
v0 user turns are scripted, not model-simulated; every scenario runs the same turns regardless
of the model's replies. Scenario spines (situation, turns, answer keys, tier) are authored by the
PI; Claude formats them to YAML and never authors items. `tests/fixtures/scenarios/` is
Claude-written plumbing data, always `status: draft`, never reported. A simulated user is a
hypothetical seam with one adapter and is not built.

## Consequences
Multi-turn realism is limited to escalation the author scripted; the caveat is stated in the EOI.
Every reported item has `reviewed_by` naming the promoting expert.
