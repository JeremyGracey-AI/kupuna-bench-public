# ADR-009: The wiki is a generated rendering of the public allowlist

## Context
A wiki makes the construct, rubric, method, and harness readable without opening files, and the
co-PI asked for one on 2026-09-08. A hand-edited wiki would be a second source of truth beside
`docs/`, and a wiki anyone can write to is a second path by which material the mirror excludes
(ADR-008) could reach the public.

## Decision
The public repository's wiki is generated, never hand-edited. `scripts/build_wiki.py` renders it
from files that the allowlist in `scripts/export_mirror.sh` already exports and refuses any other
source; the allowlist is parsed from that script, so there is one list. Four pages come from
hand-written templates in `docs/wiki/` (Home, Running the harness, Scenario format, Roadmap), which
are ordinary repository documents under the same review and export rules. Every page names its
source file and the working commit it was built from, and the footer says the wiki is regenerated
on each export. `scripts/export_wiki.sh` rebuilds the wiki checkout from a clean tree, the same
way the mirror is refreshed. Wiki editing on GitHub is restricted to collaborators. The private
working repository has no wiki: its surfaces are `HANDOFF.md`, `docs/eoi/`, and the review
workbench. With this record the allowlist grows by `SECURITY.md`, `CODE_OF_CONDUCT.md`, and
`docs/wiki/`.

## Consequences
An edit made on the wiki itself is lost at the next export; edits go to `docs/` and arrive with the
export. Pilot numbers, application drafts, the pivot brief, the handoff, and label sheets cannot
appear on the wiki because their files are not on the allowlist. The wiki moves with the mirror
when the Foundation's organization exists (ADR-001).
