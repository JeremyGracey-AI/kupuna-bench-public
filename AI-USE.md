---
ai_use_version: 1
assisted:
  - harness code, tests, CI, and documentation scaffolding (Claude Code: Claude Fable 5.1 as controller; Claude Sonnet 5 and Claude Haiku 4.5 as implementing subagents)
  - first drafts of docs/construct.md, docs/method.md, docs/rubric.md, docs/memos/, docs/decisions/, and docs/eoi/, generated from the build plan the co-PI approved on 2026-09-07
  - formatting PI-authored scenario spines into YAML (no spines exist yet)
human:
  - the design plan and every controller ruling behind the code (Jeremy Gracey, co-PI, approved 2026-09-07)
  - construct definition, severity rubric decisions, scenario spines, and gold labels (Melissa Mansfield, PhD, CPG; pending)
  - review and editing of every document before the expression of interest (scheduled 2026-09-16 to 2026-09-18; recorded as [human] commits)
review: none
accountable: Jeremy Gracey <jeremy.a.gracey@gmail.com>
updated: 2026-09-08
---

As of 2026-09-08 every document in this repository was drafted by Claude Code from a plan the
co-PI approved, and no human edit has been committed yet; `review: none` says so and flips to
`full` when the applicants' review is committed. Models under test never author evaluation items.
Rubric changes must cite a memo; the v0 memo is AI-drafted and stands only until the co-PI signs
it. The per-task record of which model produced which commit is in docs/decisions/ADR-006.
