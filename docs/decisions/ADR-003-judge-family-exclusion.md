# ADR-003: No transcript is judged by its own model family

## Context
The guidance names circular AI-as-judge as a common failure: a model grading itself or its
relatives. Anthropic provides model access, so Claude is under test.

## Decision
`run()` refuses, before any call, a judge whose `family` equals any model under test
(`JudgeFamilyConflict`). The pilot satisfies the rule by choosing a judge family not under test
at all (a Mistral-class model, with a Qwen or DeepSeek fallback if its kappa against expert
labels is poor). A two-judge panel with per-model exclusion is deferred as a hypothetical seam.

## Consequences
The judge can never be the strongest model in the roster. Judge quality is measured by
weighted kappa against expert labels, not assumed from model rank.
