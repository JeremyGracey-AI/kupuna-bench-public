# ADR-010: The judge grades one reply at a time and sees only the conversation prefix

## Context
Until 2026-09-09 the judge received the whole transcript in one call together with the scenario's
`situation`, `risk_cues`, `persona`, and the variant name, and every turn's answer key. The external
review of the mirror at 5993ca2 (held privately as docs/reviews/2026-09-09-review-5993ca2.md; finding 2) showed what that leaks: in the neutral arm the judge still
knew the person was 79 and "an older adult"; a key that expects acknowledgment of a fact the person
discloses in turn 2 was applied to turn 1; and the condition name itself was in the payload, so the
manipulation could steer the grade it was meant to measure.

## Decision
`LLMJudge` makes one call per assistant reply. The call carries the conversation up to and including
that reply, that turn's answer key (`turns[i].key`, falling back to the scenario key), and the item's
id, domain, tier, and tier definition. It carries nothing else: no variant, persona, situation, risk
cues, or later turn. The same key text is used for both variants, so the grading standard is the same
wherever the age manipulation is meant to be irrelevant. A rejected judge output is kept verbatim on
the row (`RowError.raw`, with the turn) so parser failures can be audited. `validate` warns when an
item with several turns has one shared key, because a fact disclosed later cannot be expected earlier;
a turn that is identical in both variants may be written as `user:` and carry its own key.
`situation`, `persona`, and `risk_cues` remain authoring metadata for people, not grading context.

## Consequences
Judge spend is one call per reply instead of one per transcript (about three times the pilot's $0.14).
Recorded pilot transcripts are re-judged with `regrade`; their content hashes are unchanged, so the
2026-09-08 label sheets stay valid. The two probe items keep their human-authored shared keys and now
draw the `validate` warning; giving each turn its own key is their author's call. The test fixtures
(Claude-written plumbing data) carry per-turn keys.

## Amendment, 2026-09-09
The first paid regrade of the pilot (run-2026-09-09-1, judge mistralai/mistral-large-2512) lost 16 of 48
rows to one parser rejection: the judge returned valid verdicts without the `turn` field in 16 of 96
calls. The field is redundant with the request, which fixes the graded turn, so `parse_turn_verdict`
now fills an omitted `turn` from the request and still rejects a stated turn that contradicts it. The
judge instructions are unchanged. Judge calls are not yet recorded in `Row.calls` (ADR-013 covers chat
calls), so a judge's stop reason is visible only in `RowError.raw` when parsing fails.
