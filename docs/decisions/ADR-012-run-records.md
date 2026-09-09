# ADR-012: A run claims its id first, writes its manifest before the first call, and journals every cell

## Context
The external review of the mirror at 5993ca2 found two record defects. Finding 6: `run` chose the
next record name by scanning Markdown files, overwrote the JSON sidecar, and only then created the
Markdown exclusively, so two writers could produce a JSON from one run beside a record from another,
and an orphan JSON from an interrupted write was silently replaced. Finding 5: the result kept
transcripts and verdicts but not the system prompt, the rubric's contents, the judge prompt, the
code commit, the adapters' settings, or per-call metadata, and an interrupted paid run lost every
completed cell because the progress callback only printed.

## Decision
`allocate_run` claims `results/run-YYYY-MM-DD-N/` by exclusive directory creation before any
artifact exists; N counts records, sidecars, and directories, and gaps are never refilled. The CLI
writes `manifest.json` into that directory before the first call: run id, creation time, driver,
code SHA, package and Python versions, the system prompt, the rubric's path, hash, and full contents,
the judge's instructions and context policy, judge and models with their adapter settings, runs,
draft policy, spend cap, variant order, scenarios directory, dataset hash, and scenario ids; a
regrade's manifest names its `source_run`. Every completed cell is appended to `journal.jsonl` as it
finishes, and `run --resume results/run-<id>` reuses the journaled cells verbatim (never re-emitted)
after checking the dataset hash against the manifest. The JSON sidecar is written through a temp file
and rename; the Markdown record is created exclusively last and names the run id, code SHA, and
manifest path in its front matter. The result embeds the manifest, the run id, and the source run.

## Consequences
A record is reconstructible from its manifest and journal alone. `results/run-*/` is git-ignored like
the sidecar; the committed Markdown remains the human summary. Older results JSON has no manifest and
loads unchanged (every added field has a default). Per-call metadata (completion reason, served
model, provider, request id) is added by ADR-013.
