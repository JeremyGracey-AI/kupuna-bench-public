# Method: Classic Grounded Theory as the construct-definition method

Status: v0, drafted 2026-09-07 by Claude Code from the plan the technical lead (methodologist) approved.
Answers the question "how would you
define good model behavior?": by constant comparison over expert-labeled transcripts, with
theoretical sampling as the scenario-generation policy and theoretical saturation as the stopping
rule. Glaser and Strauss abstracted this method from death-and-dying fieldwork, the substantive
area of this eval.

## The four elements, and how each is enforced

| Element | What it is here | Enforced how |
|---|---|---|
| Constant comparison | Transcripts, human labels, and judge rationales are compared continuously; memos become categories, categories become rubric revisions | `docs/memos/` is dated; `docs/rubric.yaml` carries a version and a changelog, and `tests/test_rubric.py` fails if any changelog entry does not cite an existing memo |
| Theoretical sampling | Each scenario batch is written where the emerging theory is thin, never 120 items up front | `docs/sampling-log.md` records each batch's reason; the pilot's spines are batch 1 |
| Theoretical saturation | Stop when new items stop producing new categories, and report the evidence | Saturation evidence will be a required section of the final run record (planned; the run record does not yet carry it) |
| All is data | The PI's clinical notes, labeler disagreements at the pass/fail border, judge rationales, and the older-adult interviews in the IRB study feed the same comparison | IRB plan in the full proposal; `phi-scrub` (a separate redaction tool by the technical lead, not yet wired into this harness) on any real text |

Glaser's criteria are the eval's validity criteria: **fit** (items map cleanly to a defined harm),
**work** (the eval discriminates between models; the between-model spread is the check),
**relevance** (older adults recognize the harm; the IRB validation study), **modifiability** (a
versioned taxonomy that changes only with new data, via the memo-cited changelog).

## Rubric v0 is a sensitizing default

The five criteria and the S0–S3 scale were transcribed from the brief, not discovered. They are
sensitizing concepts. The first expert-labeled seed transcripts (the pilot) are where comparison
starts; `docs/memos/2026-09-08-rubric-v0-sensitizing-default.md` records this.

## The AI-assisted discovery track, with forcing measured

A second workstream runs Classic GT over the benchmark's own data with **no construct given**. The
coders are language models from three families, each seeing incidents only, prompted with Glaser's
neutral questions and told to use no named theory. It asks "what is the main concern here, and how
is it resolved?" and may surface a core category that is not overrefusal at all. Only afterwards is
the emergent theory related to awareness contexts.

A frontier model has read Glaser, Strauss, and Timmermans, so its "emergent" codes will drift
toward that vocabulary. The model is therefore treated as a coder whose forcing risk is measured:

| Mechanism | What it does | What it cannot show |
|---|---|---|
| Blind coding | No construct, rubric, or theory names in the prompt | Does not remove the model's prior |
| Multi-family coders | Three families code the same incidents; cross-family emergence is evidence, single-family categories are that family's prior | Does not separate emergence from a prior all three share |
| Order permutation | The same incidents in random orders; does the same core category emerge? | Measures stability, not forcing |
| Memos as data | Every code carries the comparison memo that produced it; theoretical sorting stays human | |
| Saturation curve | New categories and properties per batch of five incidents, recorded in the coding result; plotting is planned | |
| Forcing audit | Overlap of emergent categories with (a) incidents open-coded blind by the PI and technical lead before seeing any model codes, and (b) named-theory and construct vocabulary | (b) alone is weak: transcripts about dying will overlap with dying vocabulary |

The blind-human comparator (a) is the strongest of these measures, and as implemented it is a
lexical diagnostic: token overlap between human code strings and category names, which a negation
does not change ("not supporting informed choice" matches "supporting informed choice"). Separating
emergence from a prior the coders share needs incident-level comparison of human and model category
assignments with semantic adjudication; that protocol is specified, not built. Coders see opaque
incident ids, every incident must be coded or marked uncodeable, and a batch that leaves incidents
uncoded is an error with no saturation point. If the human comparison has not happened, the honest
report is "prototype built, audit method specified" with no number.

What stays human: theoretical sensitivity, field sampling (thin categories in the coding result
inform the next batch, which the PI decides; automated proposals are planned), and theoretical
sorting. Coder models are named in every run; pinning exact dated model ids and recording the
served model id are planned, because a silent model update changes the analyst (ADR-005).

Prior art exists but, as far as their abstracts state, none reports a forcing measurement: Yue et
al., a tutorial on ChatGPT for grounded theory, *JMIR* 2025 (doi 10.2196/70122); Übellacker,
AcademiaOS, arXiv:2403.08844 (2024); ChatQDA, arXiv:2602.18352 (2026); and Nelson's computational
grounded theory, *Sociological Methods & Research* (doi 10.1177/0049124117729703). The forcing
audit is the contribution.
