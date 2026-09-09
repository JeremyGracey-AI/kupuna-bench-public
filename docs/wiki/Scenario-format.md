# Scenario format

The YAML a clinician writes is the most important interface in this repository. Items are authored by
the PI; Claude formats them to YAML and never authors items
(`docs/decisions/ADR-002-scripted-turns-and-authorship.md`). `scenarios/probe/` holds two
human-authored calibration items that show the format; they are never promoted or reported
(`docs/decisions/ADR-007-probe-set.md`).

## Four required fields

| Field | Values | Notes |
|---|---|---|
| `domain` | `end_of_life_planning`, `hospice_palliative`, `medications`, `driving_cessation`, `grief_bereavement`, `loneliness_companionship` | one of six |
| `tier` | `T1`, `T2`, `T3` | item stakes; see [Rubric](Rubric) |
| `turns` | a list; each turn is a quoted string, a mapping with `user` (the same text in both variants, able to carry its own `key`), or a mapping with `age_cue` and `neutral` | at least one turn must differ between the variants |
| `answer_key` | `expected` (required), `warranted_warnings`, `unwarranted_warnings`, `referral` | criteria only, never harmful specifics |

Optional: `id` (defaults to the file name), `title`, `situation`, `risk_cues`, `persona` (`age`,
`living_situation`, `cognitive_cues`, `proxy`), a per-turn `key` with the same shape as `answer_key`
(a turn without one inherits the scenario's; `validate` warns when any turn of a multi-turn item lacks its own, because
the judge grades each reply against the conversation so far and that turn's key only, and a fact
disclosed later cannot be expected earlier), `status` (`draft` by default, `reviewed`, `promoted`),
and `reviewed_by`, which `reviewed` and `promoted` require.

## Skeleton

```yaml
title: Short title
domain: medications
tier: T2
situation: Who is asking, and what they want to decide.
persona:
  age: 79
  living_situation: lives alone
  cognitive_cues: none disclosed
turns:
  - age_cue: "The request, with the later-life cue."
    neutral: "The same request without it."
  - "A follow-up that is identical in both variants."
  - age_cue: "The escalation turn."
    neutral: "The escalation turn, neutral."
    key:
      expected: What a complete, autonomy-respecting reply covers at this turn.
      warranted_warnings:
        - the risk that must be flagged here
answer_key:
  expected: What a complete, autonomy-respecting reply covers.
  warranted_warnings: []
  unwarranted_warnings:
    - crisis-line insertion
    - capacity or "have family decide" language
  referral: only when risk cues warrant it, never instead of the answer
status: draft
```

## Validation

`uv run kupuna-bench validate scenarios/v0` reports every problem in every file at once, each with
its fix in the message, for example:

```
meds-statin.yaml turns[1]: has age_cue but no neutral. A turn that differs needs both texts; an identical turn is just a quoted string.
meds-statin.yaml status: promoted needs reviewed_by. Add reviewed_by: <your name>, or set status: draft.
```

## Variants and the content hash

Every scenario runs in both variants: `age_cue` carries the later-life cue and `neutral` omits it, so
the difference in refusal and hedging is the paternalism signal. The dataset hash covers content
fields only, never `status` or `reviewed_by`, so promoting an item between a run and a regrade does
not change it.

## Promotion

`draft` items run only with `--allow-draft` and are never reported. The PI promotes an item by setting
`status: promoted` and `reviewed_by`; the runner enforces the rest.
