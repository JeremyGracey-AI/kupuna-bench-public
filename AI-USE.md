---
ai_use_version: 1
assisted:
  - harness code, tests, CI, and documentation scaffolding (Claude Code: Claude Fable 5.1 as controller; Claude Sonnet 5 and Claude Haiku 4.5 as implementing subagents)
  - first drafts of docs/construct.md, docs/method.md, docs/rubric.md, docs/memos/, docs/decisions/, and docs/eoi/, generated from the build plan the co-PI approved on 2026-09-07
  - the wiki page templates in docs/wiki/ and the generator scripts/build_wiki.py, SECURITY.md, CODE_OF_CONDUCT.md, and the issue forms in .github/ISSUE_TEMPLATE/ (2026-09-08, the polish pass the co-PI approved row by row)
  - the repository scripts (mirror and wiki export, brief render, label templates, the workbench, the gate) and the pre-commit hook in .githooks/
  - formatting human-authored scenario spines into YAML: so far the co-PI's two probe items in scenarios/probe/ (ADR-007); the PI's spines are pending
  - the 2026-09-09 response to the external review in docs/reviews/ (direction-aware agreement, prefix judging, paired contrast, blinded templates, run manifests, completion policy, coder coverage, packaged rubric; ADR-010 to ADR-013), implemented from the review's findings on the co-PI's instruction
human:
  - the design plan and every controller ruling behind the code (Jeremy Gracey, co-PI, approved 2026-09-07)
  - the two probe spines in scenarios/probe/ and the tagline heading and first sentence of docs/wiki/Home.md (Jeremy Gracey, 2026-09-08, [human] commits in the working repository; Claude replayed the wiki edit into the template)
  - construct definition, severity rubric decisions, scenario spines, and gold labels (Melissa Mansfield, PhD, CPG; pending)
  - review and editing of every document before the expression of interest (scheduled 2026-09-16 to 2026-09-18; recorded as [human] commits)
review: none
accountable: Jeremy Gracey <jeremy.a.gracey@gmail.com>
updated: 2026-09-09
---

As of 2026-09-08 every document in this repository was drafted by Claude Code from a plan the
co-PI approved; the 2026-09-09 review response was drafted the same way from the findings in
docs/reviews/. In the working repository's history (the public mirror starts fresh, ADR-008) the
only human commits so far are the co-PI's own content, not a review of that drafting: the two probe
spines, and the tagline heading and first sentence of the wiki Home template. `review: none` says so
and flips to `full` when the applicants' review of every document is committed. Models under test
never author evaluation items. Rubric changes must cite a memo; the v0 memo is AI-drafted and stands
only until the co-PI signs it. The per-task record of which model produced which commit is in
docs/decisions/ADR-006.
